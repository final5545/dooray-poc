"""슬래시 커맨드 서버 — Dooray가 호출하는 인바운드 엔드포인트.

    POST /command      /처리 실행 → 미완료 티켓 목록 + 버튼
    POST /interactive  버튼 클릭 → 업무 상태 변경 → 메시지 갱신
    GET  /health       상태 확인

⚠️ Dooray가 **우리 서버를 호출**한다. 공개 접근 가능한 URL이 필요하다.
   사내망에서는 리버스 프록시 경로를 열거나 아웃바운드 터널을 쓴다.

    export DOORAY_APP_TOKEN=<연동 서비스에서 발급한 토큰>
    python standalone/command_server.py 8910
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
load_dotenv(os.path.join(_ROOT, ".env"), override=True)

from support.command import (           # noqa: E402
    ACTION_DONE,
    build_announcement,
    build_error,
    build_result,
    build_ticket_list,
    parse_action,
)
from support.channels import (          # noqa: E402
    channel_for_member,
    direct_channels,
    me_from_channels,
)
from support.completion import news_card, reply_for_task, task_url  # noqa: E402
from support.repository import DoorayTicketRepository  # noqa: E402

APP_TOKEN = os.getenv("DOORAY_APP_TOKEN", "")
TOKEN = os.getenv("DOORAY_TOKEN", "")
PROJECT = os.getenv("DOORAY_SUPPORT_PROJECT", "")
DOMAIN = os.getenv("DOORAY_DOMAIN", "infomax.dooray.com")

repo = DoorayTicketRepository(TOKEN, PROJECT, domain=DOMAIN) if TOKEN and PROJECT else None


class Messenger:
    """요청자 개인에게 알림을 보내는 최소 클라이언트.

    본인은 Dooray! News, 남은 1:1 대화방으로 간다. 왜 그렇게 갈리는지는
    support/channels.py 참조. 채널 목록 1회로 내 memberId와 1:1 방을 한꺼번에
    얻어 캐시한다 — 소켓 토큰을 새로 발급할 필요가 없다.
    """

    def __init__(self, token: str):
        self._s = requests.Session()
        self._s.headers.update({"Authorization": f"dooray-api {token}",
                                "Content-Type": "application/json"})
        self._me = None
        self._directs = None

    def _load(self) -> None:
        if self._directs is not None:
            return
        rows = self._s.get("https://api.dooray.com/messenger/v1/channels",
                           timeout=15).json().get("result") or []
        self._me = me_from_channels(rows)
        self._directs = direct_channels(rows, self._me)
        print(f"  채널 캐시 : 나={self._me}  1:1 {len(self._directs)}건")

    def channel_for(self, member_id: str) -> str | None:
        self._load()
        return channel_for_member(member_id, self._me, self._directs)

    def send(self, channel: str, text: str, attachments: list | None = None) -> None:
        body = {"text": text}
        if attachments:
            body["attachments"] = attachments
        r = self._s.post(f"https://api.dooray.com/messenger/v1/channels/{channel}/logs",
                         json=body, timeout=15)
        r.raise_for_status()


messenger = Messenger(TOKEN) if TOKEN else None


def _authorized(payload: dict) -> bool:
    """앱 토큰 검증. 미설정이면 검증을 건너뛴다(개발 편의)."""
    if not APP_TOKEN:
        return True
    return payload.get("appToken") == APP_TOKEN


def handle_command(payload: dict) -> dict:
    """/처리 → 미완료 티켓 목록."""
    if repo is None:
        return {"responseType": "ephemeral", "text": "서버 설정이 없습니다."}
    try:
        tasks = repo.list_tasks()
    except Exception:
        return {"responseType": "ephemeral", "text": "업무 목록을 가져오지 못했습니다."}
    return build_ticket_list(tasks)


def handle_interactive(payload: dict) -> dict:
    """버튼 클릭 → 업무 상태 변경 → 목록을 그 자리에서 다시 그린다."""
    req = parse_action(payload)
    if not req:
        return build_error("처리할 수 없는 요청입니다.")
    if repo is None:
        return build_error("서버 설정이 없습니다.")

    target = req.target_state          # 되돌리기는 버튼에 실려 온 이전 상태로 간다
    if not target:
        return build_error("처리할 수 없는 요청입니다.")
    try:
        wf_id = repo.workflow_id(target)
        if not wf_id:
            return build_error("해당 상태가 프로젝트에 없습니다.")
        repo.set_workflow(req.task_id, wf_id)
    except Exception:
        return build_error("상태를 변경하지 못했습니다. 잠시 후 다시 시도해 주세요.")

    # 바뀐 뒤의 목록을 다시 읽어 화면을 갱신한다.
    # 여기서 실패해도 상태 변경 자체는 이미 성공했으므로 결과는 알려야 한다.
    try:
        tasks = repo.list_tasks()
    except Exception:
        tasks = None

    subject = ""
    if tasks:
        subject = next((t.get("subject") or "" for t in tasks
                        if str(t.get("id")) == req.task_id), "")

    # 완료는 방에 공지한다. ephemeral 결과는 누른 사람만 보므로 요청자가 모른다.
    # 수락·되돌리기는 처리자 본인의 일이라 굳이 방을 울리지 않는다.
    if req.action == ACTION_DONE:
        _announce(req, subject)
        _finish_async(req.task_id)

    return build_result(req, subject, target, tasks=tasks)


def _finish_async(task_id: str) -> None:
    """요청자 개인 통보 + 폴링 중복 방지 표식. 클릭 응답 뒤로 뺀다.

    봇 공지는 대화방에 남지만 그건 **읽지 않으면 모르는** 알림이다. 요청자가
    평소 알림을 보는 곳(Dooray! News, 또는 1:1)까지 닿아야 "그거 처리됐나요?"가
    사라진다 — 기획서 §1의 목표다.

    원래 이 통보는 에이전트의 폴링이 맡았는데, 폴링을 건너뛰게 만든 이상
    여기서 대신 보낸다. 덕분에 5분을 기다리지 않고 즉시 간다.

    조회·발신·수정으로 API 몇 번이 드므로 응답 경로에서 빼낸다. 폴링 주기가
    분 단위라 이 몇백 ms의 틈은 문제되지 않는다.
    """
    def run():
        try:
            task = repo.get(task_id)
        except Exception as e:
            print(f"    업무 조회 실패: {e}")
            return

        reply = reply_for_task(task, task_url=task_url(repo, task_id))
        if reply:
            _notify_requester(reply)

        # 표식은 통보를 보낸 뒤에 남긴다. 순서가 반대면 통보 실패 시
        # 폴링마저 건너뛰어 아무도 모르는 채로 끝난다.
        try:
            repo.mark_notified(task_id)
        except Exception as e:
            print(f"    통보 표식 실패: {e}")
    threading.Thread(target=run, daemon=True).start()


def _notify_requester(reply) -> None:
    """요청자 개인에게 완료를 알린다. 보낼 곳이 없으면 조용히 넘어간다."""
    card = news_card(reply)
    if not card or messenger is None:
        return              # 요청자 미상 — requester 줄이 없던 시절의 티켓
    try:
        channel = messenger.channel_for(reply.requester_id)
        if not channel:
            print(f"    개인 통보 생략 — 보낼 곳 없음 (member={reply.requester_id})")
            return
        messenger.send(channel, card["text"], card["attachments"])
        print(f"    개인 통보 → member={reply.requester_id}")
    except Exception as e:
        print(f"    개인 통보 실패: {e}")


def _announce(req, subject: str) -> None:
    """responseUrl로 봇 이름의 완료 공지를 보낸다. 실패해도 처리는 성공이다.

    이 URL은 **이번 호출에만 딸려 온 것**이다. 앱 토큰으로는 만들 수 없고
    (INTEGRATION_COMMAND_CALL_NOT_EXIST_ERROR), 그래서 버튼 클릭처럼 커맨드
    호출이 있는 순간에만 봇으로 말할 수 있다.
    """
    if not req.response_url or not req.channel_id:
        return
    body = build_announcement(subject)
    body["channelId"] = req.channel_id
    try:
        r = requests.post(req.response_url, json=body, timeout=10)
        ok = (r.json().get("header") or {}).get("isSuccessful")
        print(f"    완료 공지 → {'전송됨' if ok else r.text[:120]}")
    except Exception as e:
        print(f"    완료 공지 실패: {e}")


ROUTES = {"/command": handle_command, "/interactive": handle_interactive}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/health"):
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        fn = ROUTES.get(path)
        if not fn:
            self._send(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return

        print(f"  {path}  callbackId={payload.get('callbackId')} "
              f"action={payload.get('actionValue')} user={(payload.get('user') or {}).get('id')}")

        if not _authorized(payload):
            print("    ⚠️ appToken 불일치 — 거부")
            self._send(401, {"error": "unauthorized"})
            return

        try:
            result = fn(payload)
        except Exception as e:
            print(f"    처리 실패: {e}")
            result = build_error("처리 중 오류가 발생했습니다.")
        self._send(200, result)

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8910
    print("=" * 60)
    print("  슬래시 커맨드 서버")
    print("=" * 60)
    print(f"  POST /command      → 미완료 티켓 목록 + 버튼")
    print(f"  POST /interactive  → 버튼 클릭 처리")
    print(f"  GET  /health")
    print()
    print(f"  포트        : {port}")
    print(f"  프로젝트    : {PROJECT or '(미설정)'}")
    print(f"  appToken    : {'설정됨' if APP_TOKEN else '미설정 — 검증 생략'}")
    print("=" * 60)
    print()
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()

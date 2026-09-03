"""
Dooray 자체 클라이언트 (SDK 비의존)

실측(2026-09-02)으로 확인된 동작을 반영한 최소 실사용 형태.

설계 근거:
  - 소켓 토큰(JWT) 수명 1시간 → 만료 전 선제 재발급
  - 개인 계정 소켓이라 본인이 친 명령도 senderId == 본인
    → 단순 자기필터를 걸면 명령을 못 받는다.
      사람 입력은 content.token(UUID)이 있고 API 발신은 없다는 점으로 구분
  - macOS 시스템 CA 스토어 불완전 → certifi 사용 (SDK도 이걸 빠뜨려 동일 실패)
  - 초대 개념이 없어 참여 중인 모든 대화방이 유입 → 화이트리스트 필수
  - CRM 조회와 기술지원 접수가 같은 트리거(E-code)를 쓰므로 채널로 라우팅한다

사용:
    export DOORAY_TOKEN=...
    export DOORAY_ROUTES="3267267775953625054:crm,<기술팀방ID>:support"
    export DOORAY_SUPPORT_PROJECT=4412490233104336865   # support 라우트가 있을 때만
    python standalone/agent.py

DOORAY_ROUTES의 키 집합이 곧 화이트리스트다. 여기 없는 채널의 메시지는
본문을 남기지 않고 폐기한다.
"""
import json
import logging
import os
import ssl
import sys
import threading
import time

import certifi
import requests
import websocket
from dotenv import load_dotenv

# 프로젝트 루트를 import 경로에 추가하고 .env를 읽는다
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
load_dotenv(os.path.join(_ROOT, ".env"))
from crm.client import (                                 # noqa: E402
    FakeCustomerRepository,
    HttpCustomerRepository,
)
from crm.service import handle_message as crm_handle     # noqa: E402
from support.channels import channel_for_member, direct_channels  # noqa: E402
from routing import RouteConfigError, parse_routes       # noqa: E402
from support.completion import handle_news, news_card    # noqa: E402
from support.intake import PendingStore                  # noqa: E402
from support.intake import handle as intake_handle       # noqa: E402
from support.llm import OpenAICompatExtractor            # noqa: E402
from support.llm_anthropic import AnthropicExtractor      # noqa: E402
from support.repository import DoorayTicketRepository    # noqa: E402
from support.watcher import CompletionWatcher, StateStore  # noqa: E402
from support.service import handle_request as support_handle  # noqa: E402

DOMAIN = os.getenv("DOORAY_DOMAIN", "infomax.dooray.com")
TOKEN = os.getenv("DOORAY_TOKEN")
API_BASE = "https://api." + DOMAIN.split(".", 1)[1]

# 채널 → 핸들러. 키 집합이 곧 화이트리스트다.
try:
    ROUTES = parse_routes(os.getenv("DOORAY_ROUTES", ""))
except RouteConfigError as e:
    raise SystemExit(f"DOORAY_ROUTES 설정 오류: {e}")

SUPPORT_PROJECT = os.getenv("DOORAY_SUPPORT_PROJECT", "")
SUPPORT_PROJECT_CODE = os.getenv("DOORAY_SUPPORT_PROJECT_CODE", "")

# 완료 감지 폴링. Dooray가 상태 변경 알림을 주지 않아 우리가 물어봐야 한다.
POLL_INTERVAL = int(os.getenv("DOORAY_POLL_INTERVAL", "300"))       # 초
STATE_PATH = os.getenv("DOORAY_STATE_PATH", os.path.join(_ROOT, ".state", "completion.json"))

# LLM 보강 (선택). 미설정이면 규칙 기반만으로 동작한다.
# Claude(Anthropic)를 1순위로 보고, OpenAI 호환 엔드포인트는 대안으로 둔다.
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
LLM_BASE_URL = os.getenv("DOORAY_LLM_BASE_URL", "")
LLM_MODEL = os.getenv("DOORAY_LLM_MODEL", "")
LLM_API_KEY = os.getenv("DOORAY_LLM_API_KEY", "")

PING_INTERVAL = 30
TOKEN_REFRESH_MARGIN = 120   # 만료 N초 전에 미리 끊고 재발급
STANDBY_RETRY = 15           # 1008 중복 접속 시 재시도 간격 (SDK와 동일)
DEBUG_RAW = os.getenv("DOORAY_DEBUG_RAW") == "1"   # 허용 채널 원본 프레임 덤프

# content.type 실측값 (2026-09-02)
#   0=일반  1=시스템  2=봇알림(Dooray! News)  4=파일첨부  10=답글
# 답글(10)은 text가 JSON 문자열로 이중 인코딩되고, 원본 메시지는
# references.originalLogMap 에 통째로 동봉된다.
TYPE_NORMAL, TYPE_SYSTEM, TYPE_BOT, TYPE_FILE, TYPE_REPLY = 0, 1, 2, 4, 10
HANDLED_TYPES = {TYPE_NORMAL, TYPE_FILE, TYPE_REPLY}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
log = logging.getLogger("dooray")

# CRM 저장소.
#   CRM_BASE_URL 이 있으면 HTTP로 붙는다 (모의 서버 또는 실 CRM).
#   없으면 메모리 Fake — 기획서 §5 화면 예시 1건뿐이다.
# 실 CRM 전환 시 바뀌는 것은 URL과 필드 매핑뿐이고 아래 코드는 그대로다.
CRM_BASE_URL = os.getenv("CRM_BASE_URL", "")
CRM_RESULT_PATH = os.getenv("CRM_RESULT_PATH", "result")
CRM_URL_TEMPLATE = os.getenv("CRM_URL_TEMPLATE", "{base}/customers/{code}")
CRM_TIMEOUT = float(os.getenv("CRM_TIMEOUT", "2.5"))

if CRM_BASE_URL:
    CRM_REPO = HttpCustomerRepository(
        CRM_BASE_URL,
        url_template=CRM_URL_TEMPLATE,
        result_path=CRM_RESULT_PATH,
        timeout=CRM_TIMEOUT,
    )
    CRM_LABEL = f"HTTP {CRM_BASE_URL} (timeout {CRM_TIMEOUT}s)"
else:
    CRM_REPO = FakeCustomerRepository()
    CRM_LABEL = "메모리 Fake (1건)"

# 기술지원 티켓 저장소는 support 라우트가 있을 때만 만든다.
TICKET_REPO = None
WATCHER = None
if "support" in ROUTES.values():
    if not SUPPORT_PROJECT:
        raise SystemExit("support 라우트가 있으면 DOORAY_SUPPORT_PROJECT가 필요합니다.")
    TICKET_REPO = DoorayTicketRepository(TOKEN, SUPPORT_PROJECT, domain=DOMAIN)
    WATCHER = CompletionWatcher(TICKET_REPO, StateStore(STATE_PATH))

# 요청서 양식 접수 — 확인(#확인)을 기다리는 동안만 들고 있는다.
INTAKE = PendingStore()

# 기술 지원 방. 다른 방(CRM 조회)에서 낸 요청도 여기로 알린다.
SUPPORT_CHANNEL = next((ch for ch, r in ROUTES.items() if r == "support"), None)

# 자유서술 필드(고객사명·세부사항·담당자) 보강용. 없으면 규칙 기반 결과만 쓴다.
LLM = None
LLM_LABEL = "미설정 (규칙 기반만)"
if ANTHROPIC_KEY:
    LLM = AnthropicExtractor(ANTHROPIC_KEY, ANTHROPIC_MODEL)
    LLM_LABEL = f"Claude {ANTHROPIC_MODEL}"
elif LLM_BASE_URL and LLM_MODEL:
    LLM = OpenAICompatExtractor(LLM_BASE_URL, LLM_MODEL, LLM_API_KEY)
    LLM_LABEL = f"{LLM_MODEL} @ {LLM_BASE_URL}"


class DoorayClient:
    def __init__(self, token: str):
        self._token = token
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"dooray-api {token}",
            "Content-Type": "application/json",
        })
        self.member_id = None
        self._direct_cache = None

    # --- REST ---

    def fetch_socket_token(self) -> dict:
        res = self._session.post(
            f"{API_BASE}/common/v1/socket-mode/tokens", json={}, timeout=30
        )
        res.raise_for_status()
        result = res.json().get("result", {})
        self.member_id = result["organizationMemberId"]
        return result

    def reply_to_message(self, channel: str, message_id: str, text: str) -> str:
        """특정 메시지에 인용 답장."""
        res = self._session.post(
            f"{API_BASE}/messenger/v1/channels/{channel}/logs/{message_id}/reply",
            json={"text": text}, timeout=30,
        )
        res.raise_for_status()
        return res.json().get("result", {}).get("id", "")

    def send_message(self, channel: str, text: str,
                     attachments: list[dict] | None = None) -> str:
        """채널에 메시지 전송. 반환값은 생성된 메시지 ID.

        attachments를 주면 제목·링크가 붙은 카드로 렌더링된다.
        """
        payload: dict = {"text": text}
        if attachments:
            payload["attachments"] = attachments
        res = self._session.post(
            f"{API_BASE}/messenger/v1/channels/{channel}/logs",
            json=payload,
            timeout=30,
        )
        res.raise_for_status()
        return res.json().get("result", {}).get("id", "")

    def _directs(self) -> dict[str, str]:
        """{상대 memberId: 1:1 채널 ID}. 한 번 받아 캐시한다."""
        if self._direct_cache is None:
            try:
                rows = self._session.get(
                    f"{API_BASE}/messenger/v1/channels", timeout=30
                ).json().get("result") or []
            except Exception:
                log.exception("채널 목록 조회 실패")
                return {}
            self._direct_cache = direct_channels(rows, self.member_id)
            log.info("1:1 대화방 %d건 캐시", len(self._direct_cache))
        return self._direct_cache

    def notify_member(self, member_id: str, text: str,
                      attachments: list[dict] | None = None) -> bool:
        """그 사람에게 알림을 도달시킨다. 보낼 곳이 없으면 False.

        본인은 Dooray! News, 그 외는 1:1 대화방으로 간다.
        왜 그렇게 갈리는지는 support/channels.py 참조.
        """
        channel = channel_for_member(member_id, self.member_id, self._directs())
        if not channel:
            return False
        self.send_message(channel, text, attachments)
        return True


def extract_text(content: dict) -> str:
    """본문 추출. 답글은 text가 JSON 문자열이라 한 겹 벗겨야 한다."""
    raw = content.get("text") or ""
    if content.get("type") == TYPE_REPLY:
        try:
            return (json.loads(raw) or {}).get("text", "") or ""
        except (json.JSONDecodeError, TypeError, AttributeError):
            return raw     # 형식이 바뀌어도 원문으로 폴백
    return raw


def handle(client: DoorayClient, channel: str, text: str, sender: str,
           content: dict, route: str) -> None:
    """
    비즈니스 로직 진입점.

    여기 도달한 시점에 이미 화이트리스트·타입·루프 필터를 통과했다.
    실제 구현에서는 CRM 조회 등으로 교체한다.

    content로 부가 정보에 접근할 수 있다:
      - 파일 첨부  : content["file"]  (fileName / fileSize / mimeType)
      - 답글 원본  : content["originalLogId"]
    """
    # 연결 확인용. 어느 라우트에서든 동작한다.
    if text.strip() == "#ping":
        client.send_message(channel, "pong")
        return

    # 각 핸들러는 처리 대상이 아니면 None을 돌려준다 → 아무것도 보내지 않는다
    if route == "crm":
        # '#' 명령(요청서 양식)이 먼저다. 우리 명령이 아니면 None이 와서
        # 평소대로 고객번호 조회로 넘어간다.
        reply = intake_handle(
            text, channel=channel, user_id=sender, store=INTAKE,
            tickets=TICKET_REPO, customers=CRM_REPO, llm=LLM,
            origin_message=content.get("id"),
            on_created=WATCHER.track if WATCHER else None,
            announce=_announce_to_support(client, channel),
        )
        if reply is None:
            reply = crm_handle(text, CRM_REPO)
    elif route == "support":
        # requester_id는 참조자 지정용이 아니다(cc_requester 기본 False).
        #   Dooray는 상태 변경에 알림을 보내지 않아 참조자 지정의 원래 목적인
        #   완료 통보가 무효다. 대신 이 ID를 티켓 본문에 남겨 두었다가,
        #   완료됐을 때 그 사람의 Dooray! News로 우리가 직접 넣는다.
        reply = support_handle(text, TICKET_REPO, CRM_REPO, llm=LLM,
                               requester_id=sender,
                               origin_channel=channel,
                               origin_message=content.get("id"),
                               on_created=WATCHER.track if WATCHER else None)
    else:
        return

    if reply:
        client.send_message(channel, reply)


def _poll_completions(client: DoorayClient) -> None:
    """완료 감지 폴링 루프. 소켓과 별개로 돈다.

    스냅샷 비교 방식이라 주기는 지연 시간만 결정하고 누락 여부는 결정하지 않는다.
    """
    while True:
        time.sleep(POLL_INTERVAL)
        try:
            result = WATCHER.poll()
        except Exception:
            log.exception("폴링 실패")
            continue
        for reply in result.replies:
            _notify_completion(client, reply)


def _announce_to_support(client: DoorayClient, from_channel: str):
    """접수 사실을 기술 지원 방에 알리는 콜백을 만든다.

    다른 방(CRM 조회)에서 낸 요청은 기술팀 눈에 띄지 않는다. 업무만 조용히
    생기고 아무도 모르면 자동화가 아니라 사각지대다.

    같은 방에서 낸 요청이면 굳이 두 번 말하지 않는다 — 접수 회신이 이미 거기 있다.
    """
    if not SUPPORT_CHANNEL or SUPPORT_CHANNEL == from_channel:
        return None

    def announce(subject: str, task_url: str | None) -> None:
        lines = ["🆕 새 기술지원 요청이 등록되었습니다.", subject]
        if task_url:
            lines.append(task_url)
        client.send_message(SUPPORT_CHANNEL, "\n".join(lines))
        log.info("기술 지원 방 알림 → %s", subject)

    return announce


def _notify_completion(client: DoorayClient, reply) -> None:
    """완료 1건 통보 — 원 요청에 인용 답장하고, 요청자의 News에도 넣는다.

    둘은 독립적이다. 대화방 답장은 요청했던 맥락에 결과를 남기고,
    News는 그 사람이 평소 알림을 보는 곳에 도달시킨다. 한쪽이 실패해도
    다른 쪽은 보낸다.
    """
    log.info("완료 통보 → ch=%s msg=%s", reply.channel, reply.message_id)
    try:
        client.reply_to_message(reply.channel, reply.message_id, reply.text)
    except Exception:
        log.exception("완료 통보 전송 실패")

    card = news_card(reply)
    if not card:
        return              # 요청자 미상 — 이 줄이 없던 시절의 티켓
    try:
        sent = client.notify_member(reply.requester_id, card["text"], card["attachments"])
        if sent:
            log.info("개인 통보 → member=%s", reply.requester_id)
        else:
            log.info("개인 통보 생략 — 보낼 곳 없음 (member=%s)", reply.requester_id)
    except Exception:
        log.exception("개인 통보 실패 (member=%s)", reply.requester_id)


def _handle_news_frame(client: DoorayClient, frame: dict) -> None:
    """업무 완료 알림 → 원 요청 대화방에 인용 답장."""
    if TICKET_REPO is None:
        return
    try:
        reply = handle_news(frame, TICKET_REPO, SUPPORT_PROJECT_CODE or None)
    except Exception:
        log.exception("완료 알림 처리 실패")
        return
    if not reply:
        return
    _notify_completion(client, reply)


def dispatch(client: DoorayClient, frame: dict) -> None:
    """수신 프레임 1건 처리. 대상이 아니면 조용히 버린다."""
    if frame.get("type") != "channelLog":
        return

    content = frame.get("content") or {}
    channel = content.get("channelId")

    # --- Dooray! News (개인 봇 채널, channelId == 내 memberId) ---
    # 업무 완료 알림이 여기로 온다. attachments는 create가 아니라 update 프레임에
    # 채워지므로 action 필터보다 먼저 처리해야 한다.
    if channel and channel == client.member_id:
        _handle_news_frame(client, frame)
        return

    if frame.get("action") != "create":
        return

    # 라우팅 테이블 — 대상이 아니면 본문을 일절 남기지 않는다
    route = ROUTES.get(channel)
    if route is None:
        return

    if DEBUG_RAW:
        log.info("RAW %s", json.dumps(frame, ensure_ascii=False))

    msg_type = content.get("type")
    if msg_type not in HANDLED_TYPES:
        # 시스템 메시지(봇 초대/퇴장 등) 및 미지원 타입
        if DEBUG_RAW:
            log.info("skip: content.type=%r", msg_type)
        return

    sender = content.get("senderId")

    # 루프 차단: 본인 발신이면서 token 필드가 없으면 우리가 API로 보낸 응답.
    # 사람이 앱에서 친 메시지에는 token(UUID)이 붙는다.
    if sender == client.member_id and "token" not in content:
        return

    text = extract_text(content)
    if not text:
        return

    if msg_type == TYPE_FILE:
        f = content.get("file") or {}
        log.info("[%s/%s] %s: <파일> %s (%s, %s bytes)",
                 route, channel, sender, f.get("fileName"), f.get("mimeType"), f.get("fileSize"))
    else:
        log.info("[%s/%s] %s: %s", route, channel, sender, text)

    try:
        handle(client, channel, text, sender, content, route)
    except Exception:
        log.exception("handler failed")   # 사용자에게 내부 오류를 노출하지 않는다


def run_once(client: DoorayClient) -> str:
    """토큰 발급 → 연결 → 수신.

    반환값이 종료 사유이며 호출자의 재연결 간격을 결정한다.
      "refresh" : 토큰 만료 전 계획된 종료 → 즉시 재연결
      "standby" : 1008 중복 접속 → 다른 세션이 점유 중, 느린 재시도
      "error"   : 그 외 → 지수 백오프
    """
    info = client.fetch_socket_token()
    url = f"wss://{DOMAIN}/messenger/v5/ws/{info['tenantId']}/{info['organizationMemberId']}"

    # JWT exp를 읽어 만료 전에 스스로 끊는다 (SDK는 끊긴 뒤에야 재발급한다)
    import base64
    payload = info["accessToken"].split(".")[1]
    payload += "=" * (-len(payload) % 4)
    exp = json.loads(base64.urlsafe_b64decode(payload))["exp"]
    ttl = max(exp - time.time() - TOKEN_REFRESH_MARGIN, 60)
    log.info("connecting (token ttl %.0fs)", ttl)

    state = {"reason": "error"}

    def on_close(w, code, reason):
        # 계획된 갱신 종료면 scheduled_refresh가 이미 표시해 두었다
        if state["reason"] != "refresh":
            state["reason"] = "standby" if code == 1008 else "error"
        log.warning("closed code=%s reason=%s", code, reason)

    ws = websocket.WebSocketApp(
        url,
        header={"Authorization": f"Bearer {info['accessToken']}"},
        on_open=lambda w: log.info("connected"),
        on_message=lambda w, m: dispatch(client, json.loads(m)),
        on_error=lambda w, e: log.debug("ws error: %s", e),
        on_close=on_close,
    )

    def scheduled_refresh():
        time.sleep(ttl)
        log.info("token expiring — reconnecting")
        state["reason"] = "refresh"
        ws.close()

    threading.Thread(target=scheduled_refresh, daemon=True).start()

    def ping():
        while True:
            time.sleep(PING_INTERVAL)
            try:
                ws.send('{"type":"ping"}')
            except Exception:
                return

    threading.Thread(target=ping, daemon=True).start()

    ws.run_forever(
        ping_interval=PING_INTERVAL,
        ping_timeout=10,
        sslopt={"ca_certs": certifi.where()},
    )
    return state["reason"]


def main() -> None:
    if not TOKEN:
        raise SystemExit("DOORAY_TOKEN 환경변수가 없습니다.")
    if not ROUTES:
        log.warning("DOORAY_ROUTES 미설정 — 모든 메시지를 폐기합니다.")
    for ch, r in ROUTES.items():
        log.info("route %s → %s", ch, r)
    log.info("LLM 보강: %s", LLM_LABEL)
    log.info("CRM: %s", CRM_LABEL)

    client = DoorayClient(TOKEN)
    if WATCHER is not None:
        log.info("완료 감지 폴링: %d초 주기 (state=%s)", POLL_INTERVAL, STATE_PATH)
        # 소켓 연결 전에 한 번 돌려 스냅샷을 맞춰 둔다
        try:
            WATCHER.poll()
        except Exception:
            log.exception("초기 폴링 실패")
        threading.Thread(target=_poll_completions, args=(client,), daemon=True).start()

    delay = 1
    while True:
        try:
            reason = run_once(client)
        except Exception as e:
            log.error("connection failed: %s", e)
            reason = "error"

        if reason == "refresh":
            delay = 1                      # 계획된 갱신 → 즉시 재연결
        elif reason == "standby":
            # 토큰당 활성 연결 1개. 다른 세션이 점유 중이면 승격을 기다린다.
            delay = STANDBY_RETRY
            log.warning("STANDBY — 다른 세션이 토큰 점유 중. %ds 후 재시도", delay)
        else:
            delay = min(max(delay, 1) * 2, 60)

        log.info("reconnecting in %ds", delay)
        time.sleep(delay)


if __name__ == "__main__":
    main()

"""완료 통보 전 구간 검증 (소켓 전달만 제외).

  ① 원 요청 좌표를 담아 티켓 생성
  ② 완료 처리
  ③ 실제 관측된 News 프레임 형태로 합성 → handle_news 통과 확인
  ④ 실제 Dooray에 인용 답장까지 발송

    python standalone/probe_completion_e2e.py
"""
import datetime as dt
import os
import sys

import requests
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
load_dotenv(os.path.join(_ROOT, ".env"), override=True)

from crm.client import FakeCustomerRepository          # noqa: E402
from support.completion import handle_news             # noqa: E402
from support.repository import DoorayTicketRepository  # noqa: E402
from support.service import handle_request             # noqa: E402

TOKEN = os.getenv("DOORAY_TOKEN")
PID = os.getenv("DOORAY_SUPPORT_PROJECT")
SUPPORT_CH = "4412501746823008358"
H = {"Authorization": f"dooray-api {TOKEN}", "Content-Type": "application/json"}


def main() -> None:
    repo = DoorayTicketRepository(TOKEN, PID)

    print("=== 원 요청 메시지 확보 ===")
    r = requests.get(f"https://api.dooray.com/messenger/v1/channels/{SUPPORT_CH}/logs",
                     headers=H, params={"size": 1}, timeout=20)
    msg = (r.json().get("result") or [])[0]
    origin_msg = msg["id"]
    print(f"  대화방 {SUPPORT_CH} / 메시지 {origin_msg}")

    print("\n=== ① 티켓 생성 (원 요청 좌표 포함) ===")
    reply = handle_request("E230096 완료통보 전구간 검증 요청", repo,
                           FakeCustomerRepository(), dt.date(2026, 9, 2),
                           origin_channel=SUPPORT_CH, origin_message=origin_msg)
    print(" ", (reply or "").replace("\n", " / "))

    rows = requests.get(f"https://api.dooray.com/project/v1/projects/{PID}/posts",
                        headers=H, params={"size": 100}, timeout=20).json()["result"]
    task = max(rows, key=lambda p: p.get("createdAt", ""))
    task_id = task["id"]
    print(f"  taskId={task_id}  #{task.get('number')}")

    print("\n=== ② 완료 처리 ===")
    wf = requests.get(f"https://api.dooray.com/project/v1/projects/{PID}/workflows",
                      headers=H, timeout=20).json()["result"]
    closed = next(w["id"] for w in wf if w["class"] == "closed")
    requests.post(f"https://api.dooray.com/project/v1/projects/{PID}/posts/{task_id}/set-workflow",
                  headers=H, json={"workflowId": closed}, timeout=20)
    print("  완료 전환됨")

    print("\n=== ③ News 프레임 합성 → handle_news ===")
    frame = {
        "type": "channelLog", "action": "update",
        "content": {
            "channelId": "3267267451433100066", "type": 2,
            "customName": "Dooray-Bot",
            "text": 'Task [@정시욱](dooray://x/members/3362258975191542304 "member")',
            "attachments": [{
                "title": f"{task.get('taskNumber') or 'AI-PoC-Agent-Test/?'}: {task.get('subject')}",
                "titleLink": f"https://infomax.dooray.com/project/tasks/{task_id}",
            }],
        },
    }
    result = handle_news(frame, repo)
    if not result:
        sys.exit("  ❌ handle_news가 None을 반환 — 체인 실패")
    print(f"  회신 대상 : ch={result.channel} msg={result.message_id}")
    print("  회신 내용 :")
    for line in result.text.splitlines():
        print(f"    {line}")

    print("\n=== ④ 실제 인용 답장 발송 ===")
    r = requests.post(
        f"https://api.dooray.com/messenger/v1/channels/{result.channel}/logs/{result.message_id}/reply",
        headers=H, json={"text": result.text}, timeout=20)
    print(f"  HTTP {r.status_code}  {r.text[:120]}")


if __name__ == "__main__":
    main()

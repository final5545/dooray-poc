"""메시지에 버튼·카드를 넣을 수 있는지 실측.

부장님 논의사항: 메시지 안에 [수락] 같은 버튼을 두고 상태를 바꿀 수 있는가.
Dooray 검토서는 "버튼·드롭다운·카드 UI 미지원"이라고 하나,
/vote 는 실제로 버튼을 렌더링하므로 플랫폼 자체는 가능하다.
API로 노출되는지를 확인한다.

    python standalone/probe_attachments.py <channelId>
"""
import json
import os
import sys

import requests
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"), override=True)

H = {"Authorization": f"dooray-api {os.getenv('DOORAY_TOKEN')}",
     "Content-Type": "application/json"}


def send(channel: str, label: str, body: dict) -> None:
    r = requests.post(
        f"https://api.dooray.com/messenger/v1/channels/{channel}/logs",
        headers=H, json=body, timeout=20)
    ok = r.status_code == 200
    print(f"  {label:34} HTTP {r.status_code}  {'' if ok else r.text[:120]}")


def main() -> None:
    ch = sys.argv[1]

    print("=== 메시지 표현 실측 ===")

    send(ch, "1. attachments (제목·본문·색)", {
        "text": "[실측 1] attachments 기본",
        "attachments": [{
            "title": "BNK증권 신규설치",
            "titleLink": "https://infomax.dooray.com",
            "text": "고객번호 E140605 · 희망일 9/14",
            "color": "#0F6E70",
        }],
    })

    send(ch, "2. attachments + actions (버튼)", {
        "text": "[실측 2] 버튼 시도",
        "attachments": [{
            "title": "기술지원 요청",
            "text": "상태를 변경하세요",
            "callbackId": "ticket-42",
            "actions": [
                {"type": "button", "name": "accept", "text": "수락", "value": "accept"},
                {"type": "button", "name": "done", "text": "완료", "value": "done"},
            ],
        }],
    })

    send(ch, "3. fields (라벨-값 표)", {
        "text": "[실측 3] fields",
        "attachments": [{
            "title": "고객정보",
            "fields": [
                {"title": "고객명", "value": "비엔케이자산운용", "short": True},
                {"title": "등급", "value": "계약", "short": True},
            ],
        }],
    })

    send(ch, "4. 마크다운 하이퍼링크", {
        "text": "[실측 4] 완료 처리하려면 [여기를 누르세요]"
                "(https://infomax.dooray.com/project/tasks/4412603105543031023)",
    })

    print("\nDooray 화면에서 어떻게 렌더링되는지 확인 필요")


if __name__ == "__main__":
    main()

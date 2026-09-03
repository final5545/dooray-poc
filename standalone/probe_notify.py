"""업무 알림이 메신저 소켓으로 도달하는지 확인 (본문 미수집).

정원석님 관찰: 업무에 참조자/담당자로 추가되면 Dooray 알림이 뜬다.
그 알림이 메신저 채널(Dooray! News 등)로 오는지, 즉 우리 소켓이 읽을 수 있는지를 본다.

⚠️ 개인정보 보호: 대화 본문은 기록하지 않는다.
   채널 메타데이터와 프레임 종류만 남기고, 봇 발신 메시지만 본문을 보여준다.

    python standalone/probe_notify.go.py
"""
import json
import os
import ssl
import sys
import threading
import time

import certifi
import requests
import websocket
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"), override=True)

TOKEN = os.getenv("DOORAY_TOKEN")
DOMAIN = os.getenv("DOORAY_DOMAIN", "infomax.dooray.com")
API_BASE = "https://api." + DOMAIN.split(".", 1)[1]
PING_INTERVAL = 30

# 이 채널들만 본문을 표시한다 (우리 테스트 채널)
SHOW_TEXT = {
    "4412656458220431595",   # CRM 조회
    "4412501746823008358",   # 기술 지원 현황판
}


def describe(frame: dict) -> str | None:
    """프레임 1건 → 한 줄 요약. 관심 없는 종류는 None."""
    t = frame.get("type")
    if t in ("pong", "channelMemberReadSeq"):
        return None

    content = frame.get("content") or {}
    cid = content.get("channelId") or frame.get("channelId") or "-"
    cm = (frame.get("references") or {}).get("channelMap") or {}
    meta = next(iter(cm.values()), {}) if cm else {}
    title = meta.get("title") or ""
    ctype = meta.get("type") or (frame.get("channel") or {}).get("type") or "?"

    line = (f"type={t} action={frame.get('action')} "
            f"ch={cid} chType={ctype} title={title!r}")

    if t == "channelLog":
        sender = content.get("senderId")
        # 봇 발신(사람이 친 게 아닌 것)은 token 필드가 없다 → 알림 후보
        is_bot = "token" not in content
        line += f" sender={sender} bot={is_bot}"
        if cid in SHOW_TEXT or is_bot:
            line += f"\n      text={(content.get('text') or '')[:200]!r}"
        else:
            line += "  (본문 미수집)"
    return line


def main() -> None:
    if not TOKEN:
        sys.exit("DOORAY_TOKEN 없음")

    res = requests.post(f"{API_BASE}/common/v1/socket-mode/tokens",
                        headers={"Authorization": f"dooray-api {TOKEN}",
                                 "Content-Type": "application/json"},
                        json={}, timeout=30)
    res.raise_for_status()
    info = res.json()["result"]
    url = f"wss://{DOMAIN}/messenger/v5/ws/{info['tenantId']}/{info['organizationMemberId']}"
    print(f"연결: {url}\n")
    print("업무 알림이 소켓으로 오는지 관찰합니다. 대화 본문은 기록하지 않습니다.")
    print("-" * 70)

    def on_open(ws):
        print("연결됨. 이제 업무에 참조자/담당자를 추가해 보세요.\n")

        def ping():
            while True:
                time.sleep(PING_INTERVAL)
                try:
                    ws.send('{"type":"ping"}')
                except Exception:
                    return
        threading.Thread(target=ping, daemon=True).start()

    def on_message(ws, message):
        try:
            frame = json.loads(message)
        except json.JSONDecodeError:
            return

        # Dooray! News(개인 봇 채널)는 전문을 본다 — 봇 알림이라 개인정보가 아니다.
        # 채널 ID가 곧 내 memberId다.
        content = frame.get("content") or {}
        cid = content.get("channelId") or ""
        cm = (frame.get("references") or {}).get("channelMap") or {}
        meta = next(iter(cm.values()), {}) if cm else {}
        is_news = (cid == info["organizationMemberId"]
                   or meta.get("type") == "bot"
                   or meta.get("title") == "Dooray! News")

        # 관심 채널은 전문을 본다 (버튼 클릭 이벤트 구조 확인용)
        if cid in SHOW_TEXT:
            print(f"\n[{time.strftime('%H:%M:%S')}] ===== {cid} 전문 =====")
            print(json.dumps(frame, ensure_ascii=False, indent=2)[:3000])
            print("=" * 60)
            return

        if is_news and frame.get("type") == "channelLog":
            print(f"\n[{time.strftime('%H:%M:%S')}] ===== Dooray! News 전문 =====")
            print(json.dumps(frame, ensure_ascii=False, indent=2)[:4000])
            print("=" * 60)
            return

        line = describe(frame)
        if line:
            print(f"[{time.strftime('%H:%M:%S')}] {line}")

    websocket.WebSocketApp(
        url,
        header={"Authorization": f"Bearer {info['accessToken']}"},
        on_open=on_open,
        on_message=on_message,
        on_error=lambda w, e: print(f"[error] {e}"),
        on_close=lambda w, c, r: print(f"[closed] {c}"),
    ).run_forever(ping_interval=PING_INTERVAL, ping_timeout=10,
                  sslopt={"ca_certs": certifi.where()})


if __name__ == "__main__":
    main()

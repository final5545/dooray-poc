"""
Dooray Socket Mode 자체 구현 프로브 (SDK 비의존)

목적: 개인 액세스 토큰으로 Socket Mode 접속이 가능한지 판별하고,
      가능하다면 WebSocket 원본 프레임을 그대로 덤프한다.

SDK는 sessionInfo / content.type==1 / channelLog 이외 프레임을 버리므로
페이로드 구조 탐색(03-poc-진행현황.md §6)에는 원본 덤프가 필요하다.

사용:
    export DOORAY_TOKEN=...          # 개인 액세스 토큰
    python standalone/probe.py
"""
import json
import os
import sys
import threading
import time

import certifi
import requests
import websocket

DOMAIN = os.getenv("DOORAY_DOMAIN", "infomax.dooray.com")
TOKEN = os.getenv("DOORAY_TOKEN")
API_BASE = "https://api." + DOMAIN.split(".", 1)[1]
PING_INTERVAL = 30


def fetch_socket_token():
    """① 토큰 교환. 여기서 401/403이면 이 전략은 성립하지 않는다."""
    url = f"{API_BASE}/common/v1/socket-mode/tokens"
    print(f"[1] POST {url}")

    res = requests.post(
        url,
        headers={
            "Authorization": f"dooray-api {TOKEN}",
            "Content-Type": "application/json",
        },
        json={},
        timeout=30,
    )
    print(f"    HTTP {res.status_code}")

    if res.status_code != 200:
        print(f"    body: {res.text[:500]}")
        print("\n>>> 판정: 개인 액세스 토큰으로는 Socket Mode 발급 불가.")
        print(">>> 에이전트 토큰(AI 프리미엄 라이선스)이 필요하다는 뜻.")
        sys.exit(1)

    body = res.json()
    result = body.get("result", {})
    missing = [k for k in ("accessToken", "tenantId", "organizationMemberId")
               if not result.get(k)]
    if missing:
        print(f"    응답에 필드 누락: {missing}")
        print(f"    raw: {json.dumps(body, ensure_ascii=False)[:500]}")
        sys.exit(1)

    print(f"    tenantId={result['tenantId']} memberId={result['organizationMemberId']}")
    print(">>> 판정: 개인 액세스 토큰으로 Socket Mode 발급 성공.\n")
    return result


def main():
    if not TOKEN:
        print("DOORAY_TOKEN 환경변수가 없습니다.")
        sys.exit(1)

    info = fetch_socket_token()
    ws_url = f"wss://{DOMAIN}/messenger/v5/ws/{info['tenantId']}/{info['organizationMemberId']}"
    print(f"[2] CONNECT {ws_url}\n")

    def on_open(ws):
        print("--- connected. 메시지를 보내보세요 (Ctrl+C 종료) ---\n")

        def ping():
            while True:
                time.sleep(PING_INTERVAL)
                try:
                    ws.send('{"type":"ping"}')
                except Exception:
                    return

        threading.Thread(target=ping, daemon=True).start()

    def on_message(ws, message):
        # 원본 그대로 출력 — SDK가 버리는 프레임까지 전부 본다
        try:
            parsed = json.loads(message)
            print(json.dumps(parsed, ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            print(f"[non-json] {message}")
        print("-" * 60)

    def on_error(ws, error):
        print(f"[error] {error}")

    def on_close(ws, code, msg):
        print(f"[closed] code={code} reason={msg}")
        if code == 1008:
            print(">>> 1008: 동일 토큰으로 이미 접속된 세션이 있습니다.")

    websocket.WebSocketApp(
        ws_url,
        header={"Authorization": f"Bearer {info['accessToken']}"},
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    ).run_forever(
        ping_interval=PING_INTERVAL,
        ping_timeout=10,
        # macOS 시스템 CA 스토어가 불완전해 검증 실패 → certifi 번들 사용.
        # SDK(socket_mode/client.py)는 sslopt를 넘기지 않아 같은 환경에서 동일하게 실패한다.
        sslopt={"ca_certs": certifi.where()},
    )


if __name__ == "__main__":
    main()

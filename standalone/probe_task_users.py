"""업무에 담당자/참조자를 지정할 수 있는지 확인.

지정이 되면 Dooray가 상태 변경 시 자체적으로 알림을 보낸다.
그러면 watcher(폴링)가 필요 없어진다.

    python standalone/probe_task_users.py <projectId>
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
B = "https://api.dooray.com/project/v1/projects"
ME = "3267267451433100066"


def main() -> None:
    pid = sys.argv[1]

    print("=== 프로젝트 멤버 조회 ===")
    r = requests.get(f"{B}/{pid}/members", headers=H, params={"size": 10}, timeout=20)
    print(f"  HTTP {r.status_code}  {r.text[:200]}")

    print("\n=== 담당자(to) + 참조자(cc) 지정해서 업무 생성 ===")
    body = {
        "subject": "[알림테스트] 담당자·참조자 지정",
        "body": {"mimeType": "text/x-markdown",
                 "content": "Dooray 자체 알림이 오는지 확인용. 완료 처리 시 알림 확인."},
        "users": {
            "to": [{"type": "member", "member": {"organizationMemberId": ME}}],
            "cc": [{"type": "member", "member": {"organizationMemberId": ME}}],
        },
    }
    r = requests.post(f"{B}/{pid}/posts", headers=H, json=body, timeout=20)
    print(f"  HTTP {r.status_code}  {r.text[:200]}")
    if r.status_code != 200:
        return
    post_id = (r.json().get("result") or {}).get("id")

    print("\n=== 생성 결과의 users 필드 ===")
    d = requests.get(f"{B}/{pid}/posts/{post_id}", headers=H, timeout=20).json().get("result", {})
    print(json.dumps(d.get("users"), ensure_ascii=False, indent=2)[:800])
    print(f"\n  postId={post_id}")


if __name__ == "__main__":
    main()

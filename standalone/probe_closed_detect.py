"""'완료로 변경' 감지 검증.

현황판(Dooray 프로젝트)에서 업무를 완료 처리했을 때
폴링으로 그 변화를 잡아낼 수 있는지 확인한다.

    python standalone/probe_closed_detect.py <projectId>
"""
import os
import sys

import requests
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"), override=True)

H = {"Authorization": f"dooray-api {os.getenv('DOORAY_TOKEN')}",
     "Content-Type": "application/json"}
B = "https://api.dooray.com/project/v1/projects"


def snapshot(pid: str) -> dict:
    """{postId: (workflowClass, closed, updatedAt, subject)} — 목록 1회 호출."""
    r = requests.get(f"{B}/{pid}/posts", headers=H, params={"size": 100}, timeout=20)
    r.raise_for_status()
    return {p["id"]: (p.get("workflowClass"), p.get("closed"),
                      p.get("updatedAt"), p.get("subject"))
            for p in (r.json().get("result") or [])}


def main() -> None:
    pid = sys.argv[1]

    before = snapshot(pid)
    print(f"=== 변경 전 스냅샷 ({len(before)}건) ===")
    for k, v in before.items():
        print(f"  {v[0]:11} closed={str(v[1]):5} {v[3][:38]!r}")

    # 첫 미완료 건을 완료로 전환
    target = next((k for k, v in before.items() if not v[1]), None)
    if not target:
        sys.exit("미완료 건이 없습니다.")

    wf = requests.get(f"{B}/{pid}/workflows", headers=H, timeout=20).json().get("result") or []
    closed_id = next(w["id"] for w in wf if w.get("class") == "closed")

    print(f"\n=== '완료'로 전환: {before[target][3][:40]!r} ===")
    r = requests.post(f"{B}/{pid}/posts/{target}/set-workflow", headers=H,
                      json={"workflowId": closed_id}, timeout=20)
    print(f"  HTTP {r.status_code}")

    after = snapshot(pid)
    print("\n=== 변경 후 diff ===")
    found = False
    for k, v in after.items():
        old = before.get(k)
        if old and old[:2] != v[:2]:
            found = True
            print(f"  🔔 감지: {v[3][:38]!r}")
            print(f"       {old[0]}(closed={old[1]}) → {v[0]}(closed={v[1]})")
            print(f"       updatedAt {old[2]} → {v[2]}")
    if not found:
        print("  변화 감지 실패")

    print("\n=== closed 필터 동작 확인 ===")
    r = requests.get(f"{B}/{pid}/posts", headers=H,
                     params={"size": 100, "postWorkflowClasses": "closed"}, timeout=20)
    rows = r.json().get("result") or []
    print(f"  postWorkflowClasses=closed → {len(rows)}건")
    for p in rows:
        print(f"    #{p.get('number')} {p.get('workflowClass')} {str(p.get('subject'))[:38]!r}")


if __name__ == "__main__":
    main()

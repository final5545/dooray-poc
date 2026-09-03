"""기술지원 기획서 §3~4 시나리오를 REST로 재현한다.

  ① 워크플로 정의 확인
  ② 업무(티켓) 생성 — 기획서 §2 예시 형태의 제목
  ③ 상태 전환 (접수 → 진행 중)
  ④ 결과 조회

    export DOORAY_TOKEN=...
    python standalone/probe_task_flow.py <projectId>
"""
import json
import os
import sys

import requests

TOKEN = os.getenv("DOORAY_TOKEN")
BASE = "https://api.dooray.com"
H = {"Authorization": f"dooray-api {TOKEN}", "Content-Type": "application/json"}


def show(label, r):
    print(f"{label}  HTTP {r.status_code}")
    try:
        d = r.json()
        print("   ", json.dumps(d.get("result") or d.get("header"), ensure_ascii=False)[:300])
        return d
    except Exception:
        print("   ", r.text[:200])
        return {}


def main() -> None:
    if not TOKEN:
        sys.exit("DOORAY_TOKEN 환경변수가 없습니다.")
    if len(sys.argv) < 2:
        sys.exit("사용법: probe_task_flow.py <projectId>")
    pid = sys.argv[1]

    print("=== ① 워크플로 정의 ===")
    r = requests.get(f"{BASE}/project/v1/projects/{pid}/workflows", headers=H, timeout=20)
    flows = (r.json().get("result") or []) if r.status_code == 200 else []
    for w in flows:
        print(f"    id={w.get('id')}  name={w.get('name')!r}  class={w.get('class')!r}  order={w.get('order')}")
    by_class = {w.get("class"): w for w in flows}

    print("\n=== ② 업무 생성 ===")
    # 기획서 §2 예시: "BNK증권 신규설치 [방문예정 8/14]"
    body = {
        "subject": "BNK증권 신규설치 [방문예정 8/14]",
        "body": {
            "mimeType": "text/x-markdown",
            "content": (
                "[기본정보]\n"
                "고객사 : BNK증권\n"
                "고객 고유번호 : E140605\n"
                "[요청정보]\n"
                "요청 유형 : 신규설치\n"
                "희망일 : 2026-08-14\n"
                "\n(AI 자동 등록 — PoC 검증용)"
            ),
        },
    }
    r = requests.post(f"{BASE}/project/v1/projects/{pid}/posts", headers=H, json=body, timeout=30)
    d = show("    POST .../posts", r)
    post_id = (d.get("result") or {}).get("id")
    if not post_id:
        sys.exit("업무 생성 실패 — 이후 단계 중단")
    print(f"    → postId={post_id}")

    print("\n=== ③ 상태 전환 (→ working) ===")
    target = by_class.get("working")
    if not target:
        print("    working 워크플로가 없어 건너뜀")
    else:
        r = requests.post(
            f"{BASE}/project/v1/projects/{pid}/posts/{post_id}/set-workflow",
            headers=H, json={"workflowId": target["id"]}, timeout=30)
        show(f"    set-workflow → {target['name']!r}", r)

    print("\n=== ④ 결과 조회 ===")
    r = requests.get(f"{BASE}/project/v1/projects/{pid}/posts/{post_id}", headers=H, timeout=20)
    if r.status_code == 200:
        res = r.json().get("result") or {}
        wf = (res.get("workflow") or {})
        print(f"    번호   : {res.get('number')}")
        print(f"    제목   : {res.get('subject')!r}")
        print(f"    상태   : {wf.get('name')!r} (class={wf.get('class')!r})")
        print(f"    작성자 : {((res.get('users') or {}).get('from') or {}).get('member', {}).get('name')}")
    else:
        show("    GET post", r)


if __name__ == "__main__":
    main()

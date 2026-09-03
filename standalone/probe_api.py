"""Dooray REST API 지원 범위 탐색 (조회 전용).

기술지원 기획서의 '현황판(Dooray! News) 티켓 자동 등록'이
Task API에 의존하는데, SDK 패키지에는 있으나 공식 문서에 없다(03 §8 갭 #1).
개인 액세스 토큰으로 REST에서 실제 동작하는지 확인한다.

    export DOORAY_TOKEN=...
    python standalone/probe_api.py
"""
import os
import sys

import requests

TOKEN = os.getenv("DOORAY_TOKEN")
BASE = "https://api.dooray.com"


def probe(path: str, params: dict | None = None):
    try:
        r = requests.get(BASE + path, headers={"Authorization": f"dooray-api {TOKEN}"},
                         params=params or {}, timeout=20)
    except Exception as e:
        print(f"  {path:38} EXC  {e}")
        return None

    try:
        d = r.json()
        hdr = d.get("header", {}) or {}
        res = d.get("result")
        n = len(res) if isinstance(res, list) else ("dict" if res else "-")
        info = f"code={hdr.get('resultCode')} result={n} msg={str(hdr.get('resultMessage',''))[:40]!r}"
    except Exception:
        info = r.text[:70].replace("\n", " ")
    print(f"  {path:38} HTTP {r.status_code}  {info}")
    return r


def main() -> None:
    if not TOKEN:
        sys.exit("DOORAY_TOKEN 환경변수가 없습니다.")

    print("=== 프로젝트(업무) ===")
    r = probe("/project/v1/projects", {"size": 10, "member": "me"})
    probe("/project/v1/projects", {"size": 5})

    print("\n=== 위키 ===")
    probe("/wiki/v1/wikis", {"size": 10})

    print("\n=== 현황판(News) 후보 경로 ===")
    # 기술지원 기획서는 '현황판(Dooray! News)'을 전제하나
    # SDK가 제공하는 것은 Task/Wiki 뿐이다(00 §9). REST에 별도 경로가 있는지 확인.
    for path in ("/news/v1/news", "/news/v1/posts", "/board/v1/boards"):
        probe(path, {"size": 3})

    print("\n=== 조직 ===")
    probe("/common/v1/members", {"size": 3})

    if r is not None and r.status_code == 200:
        rows = r.json().get("result") or []
        print(f"\n=== 참여 프로젝트 {len(rows)}건 ===")
        for p in rows:
            print(f"  id={p.get('id')}  code={p.get('code')!r}  "
                  f"state={p.get('state')!r}  scope={p.get('scope')!r}")


def inspect_project(pid: str) -> None:
    """기술지원 기획서 §4 상태 흐름과 매핑하기 위해 워크플로 정의를 본다."""
    print(f"\n=== 워크플로 정의 (project {pid}) ===")
    r = probe(f"/project/v1/projects/{pid}/workflows")
    if r is not None and r.status_code == 200:
        for w in (r.json().get("result") or []):
            print(f"  id={w.get('id')}  name={w.get('name')!r}  "
                  f"class={w.get('class')!r}  order={w.get('order')}")

    print(f"\n=== 업무 목록 (project {pid}) ===")
    probe(f"/project/v1/projects/{pid}/posts", {"size": 3})


if __name__ == "__main__":
    main()
    if len(sys.argv) > 1:
        inspect_project(sys.argv[1])

"""PoC 테스트용 프로젝트 생성 (쓰기 작업).

기술지원 기획서의 '현황판 티켓 자동 등록'이 REST로 실제 되는지 검증하기 위한
격리된 프로젝트를 만든다. 실제 업무 프로젝트를 건드리지 않기 위함이다.

    export DOORAY_TOKEN=...
    python standalone/create_test_project.py
"""
import json
import os
import sys

import requests

TOKEN = os.getenv("DOORAY_TOKEN")
BASE = "https://api.dooray.com"

CODE = "AI-PoC-Agent-Test"
DESCRIPTION = "Dooray Extension Agent PoC 검증용. 테스트 후 삭제 예정."


def main() -> None:
    if not TOKEN:
        sys.exit("DOORAY_TOKEN 환경변수가 없습니다.")

    headers = {
        "Authorization": f"dooray-api {TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"code": CODE, "description": DESCRIPTION, "scope": "private"}

    print(f"POST /project/v1/projects  code={CODE!r}")
    r = requests.post(f"{BASE}/project/v1/projects", headers=headers,
                      json=payload, timeout=30)
    print(f"HTTP {r.status_code}")
    try:
        print(json.dumps(r.json(), ensure_ascii=False, indent=2)[:800])
    except Exception:
        print(r.text[:500])


if __name__ == "__main__":
    main()

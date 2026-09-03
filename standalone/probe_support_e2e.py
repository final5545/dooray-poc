"""기술지원 자동화 통합 검증 — 실제 Dooray 프로젝트에 티켓을 등록한다.

    export DOORAY_TOKEN=...
    python standalone/probe_support_e2e.py <projectId>
"""
import datetime as dt
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv                         # noqa: E402
load_dotenv(os.path.join(_ROOT, ".env"), override=True)

from crm.client import FakeCustomerRepository          # noqa: E402
from support.llm_anthropic import AnthropicExtractor   # noqa: E402
from support.repository import DoorayTicketRepository  # noqa: E402
from support.service import handle_request             # noqa: E402

REQUEST = """비엔케이자산운용
E21016, E200105 층내 이전 요청으로 부탁드립니다.
희망일정 : 9월 15일(화) 오후 4시 이후
담당자 : 김수빈 파트너"""


def main() -> None:
    token = os.getenv("DOORAY_TOKEN")
    if not token or len(sys.argv) < 2:
        sys.exit("사용법: DOORAY_TOKEN=... probe_support_e2e.py <projectId>")

    repo = DoorayTicketRepository(token, sys.argv[1])

    print("=== 요청문 ===")
    print(REQUEST)

    print("\n=== 처리 ===")
    key = os.getenv("ANTHROPIC_API_KEY", "")
    model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
    llm = AnthropicExtractor(key, model) if key else None
    print(f"LLM: {'Claude ' + model if llm else '미설정'}")

    reply = handle_request(REQUEST, repo, FakeCustomerRepository(),
                           dt.date(2026, 9, 2), llm=llm)
    print(reply)

    print("\n=== 워크플로 확인 ===")
    for w in repo.list_workflows():
        print(f"  {w.get('class'):11} {w.get('name')!r}")
    print(f"  registered ID = {repo.workflow_id('registered')}")


if __name__ == "__main__":
    main()

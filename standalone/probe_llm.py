"""Claude 보강 실측 — 실제 API를 호출한다.

    python standalone/probe_llm.py
"""
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv                          # noqa: E402
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from support.extractor import extract                   # noqa: E402
from support.llm_anthropic import AnthropicExtractor    # noqa: E402

TODAY = dt.date(2026, 9, 2)

CASES = [
    """비엔케이자산운용
E21016, E200105 층내 이전 요청으로 부탁드립니다.
희망일정 : 8월 28일(금) 오후 4시 이후
담당자 : 김수빈 파트너 010-6265-4782""",

    """E140605 에이치라인해운 자금기획팀
1882 엑셀 2016버전 업그레이드 부탁""",

    """한국거래소 파생시장부(부산) 윈도우데이트부탁드립니다.
김재영 차장: E050282
최재원 대리: E050102""",

    "E230096 저희 단말기가 계속 튕기는데 좀 봐주세요",
]


def main() -> None:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
    if not key:
        sys.exit("ANTHROPIC_API_KEY 없음")

    llm = AnthropicExtractor(key, model)
    print(f"모델: {model}\n")

    total = 0.0
    for i, text in enumerate(CASES, 1):
        base = extract(text, TODAY)
        t0 = time.perf_counter()
        enr = llm.enrich(text, base)
        elapsed = time.perf_counter() - t0
        total += elapsed

        print(f"--- 케이스 {i} ({elapsed:.2f}s) ---")
        print(f"  원문   : {text.splitlines()[0][:40]}...")
        print(f"  [규칙] 코드={base.customer_codes} 유형={base.request_type!r} 날짜={base.desired_date}")
        print(f"  [LLM ] 고객사={enr.customer_name!r}")
        print(f"         유형={enr.request_type!r}")
        print(f"         세부={enr.detail!r}")
        print(f"         담당={enr.contact!r}")

    print(f"\n평균 {total/len(CASES):.2f}s / 건")


if __name__ == "__main__":
    main()

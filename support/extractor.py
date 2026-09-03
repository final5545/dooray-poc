"""기술지원 요청문에서 핵심 데이터를 추출한다.

기획서 §2 "데이터 자동 추출 (AI)" — 요청 유형 / 고객번호 / 희망일.

⚠️ 기획서는 'AI가 분석'으로 적고 있으나, 고객번호·날짜처럼 형식이 고정된 값은
   정규식이 더 빠르고 정확하며 비용이 없다(01 §6, 05 §7의 판단과 동일).
   LLM은 '세부 사항' 요약처럼 자유서술이 필요한 부분에만 쓰는 것이 맞다.
   → 여기서는 규칙 기반으로 확정 가능한 것만 뽑고, 세부사항은 원문을 남긴다.
"""
import datetime as _dt
import re
from dataclasses import dataclass, field

from crm.parser import parse_all_customer_codes

# 요청 유형 분류.
#   CRM 기획서 §3 단계5의 양식 분류 +
#   기술지원 기획서 §5 화면 예시의 실제 요청문에서 관측된 표현.
# 순서가 우선순위다. 먼저 매칭되는 유형을 채택한다.
REQUEST_TYPES: list[tuple[str, tuple[str, ...]]] = [
    ("장비/설비 이전", ("층내 이전", "이전", "이동", "이설")),
    ("SW 업그레이드", ("업그레이드", "업데이트", "윈도우", "버전", "패치")),
    ("신규설치", ("신규설치", "신규 설치", "신규", "설치")),
    ("노후교체", ("노후", "교체")),
    ("장애", ("장애", "오류", "에러", "먹통", "안됩니다", "안 됩니다")),
    ("회수", ("회수", "철거", "반납")),
    ("시험아이디 발급", ("시험아이디", "시험 아이디", "체험아이디")),
    ("해지", ("해지",)),
    ("전환", ("전환",)),
    ("청구변경", ("청구변경", "청구 변경", "청구보류", "재개")),
    ("세금계산서", ("세금계산서",)),
]

_DATE_PATTERNS = (
    re.compile(r"(?P<y>\d{4})[-./](?P<m>\d{1,2})[-./](?P<d>\d{1,2})"),
    re.compile(r"(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"),
    re.compile(r"\b(?P<m>\d{1,2})/(?P<d>\d{1,2})\b"),
)

# "희망일정 : 8월 28일(금) 오후 4시 이후" 처럼 라벨이 붙는 경우가 많다.
_DESIRED_LABEL = re.compile(r"희망\s*(?:일정|일자|일)\s*[:：]?\s*(?P<rest>.+)")


@dataclass
class SupportRequest:
    """추출 결과. 비즈니스 판단은 하지 않고 값만 담는다."""
    customer_codes: list[str] = field(default_factory=list)
    request_type: str | None = None
    desired_date: _dt.date | None = None
    desired_raw: str | None = None      # 원문 표현 ("8월 28일(금) 오후 4시 이후")
    raw_text: str = ""

    @property
    def is_actionable(self) -> bool:
        """티켓을 만들 만한 최소 정보가 있는가.

        고객번호가 없으면 어느 고객 건인지 특정할 수 없어 티켓 가치가 없다.
        """
        return bool(self.customer_codes)


def extract_request_type(text: str) -> str | None:
    if not text:
        return None
    for label, keywords in REQUEST_TYPES:
        if any(k in text for k in keywords):
            return label
    return None


def _to_date(m: re.Match, today: _dt.date) -> _dt.date | None:
    try:
        year = int(m.groupdict().get("y") or 0)
        month, day = int(m.group("m")), int(m.group("d"))
        if year:
            return _dt.date(year, month, day)
        # 연도가 없으면 올해로 보되, 이미 한참 지난 날짜면 내년으로 해석한다.
        candidate = _dt.date(today.year, month, day)
        if (today - candidate).days > 180:
            candidate = _dt.date(today.year + 1, month, day)
        return candidate
    except ValueError:
        return None      # 2월 30일 같은 값


def extract_desired_date(text: str, today: _dt.date | None = None
                         ) -> tuple[_dt.date | None, str | None]:
    """희망일을 (날짜, 원문표현)으로 반환.

    '희망일정 :' 라벨이 있으면 그 뒤를 우선 탐색한다. 없으면 전체에서 찾는다.
    """
    if not text:
        return None, None
    today = today or _dt.date.today()

    label = _DESIRED_LABEL.search(text)
    scopes = [label.group("rest")] if label else []
    scopes.append(text)

    for scope in scopes:
        for pattern in _DATE_PATTERNS:
            m = pattern.search(scope)
            if not m:
                continue
            parsed = _to_date(m, today)
            if parsed:
                raw = label.group("rest").strip() if label else m.group(0)
                return parsed, raw
    return None, (label.group("rest").strip() if label else None)


def extract(text: str, today: _dt.date | None = None) -> SupportRequest:
    """요청문 1건 → 추출 결과."""
    text = text or ""
    date, raw = extract_desired_date(text, today)
    return SupportRequest(
        customer_codes=parse_all_customer_codes(text),
        request_type=extract_request_type(text),
        desired_date=date,
        desired_raw=raw,
        raw_text=text.strip(),
    )

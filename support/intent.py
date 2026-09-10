"""무엇을 하려는 말인가 — 조회인가 요청인가.

CRM 조회 방에서는 고객번호가 든 메시지가 두 가지 뜻을 가진다.

    "E230096 계약 언제 끝나지?"   →  고객정보를 보고 싶다
    "E230096 이전 요청할래"        →  기술지원을 요청하고 싶다

지금까지는 전자만 가정하고 무조건 고객 카드를 뱉었다. 요청을 하려면 #이전 로
양식을 받아 손으로 채워야 했는데, 시연 회의에서 "말하듯 쓰면 알아서 되게"라는
요구가 나왔다.

⚠️ **규칙이 넓게 걸러 내고, LLM이 좁혀 판정한다.**
   규칙(might_be_request)의 목적은 정확한 판정이 아니라 '명백히 요청이 아닌
   것'만 걸러 호출을 줄이는 것이다. 좁게 잡으면 진짜 요청을 놓치는데 그건
   되돌릴 방법이 없고, 넓게 잡아 생긴 오탐은 LLM이 조회로 눕혀 준다.

⚠️ **자동으로 업무를 만들지는 않는다.**
   LLM이 잘못 읽을 수 있고, 두레이에는 업무 삭제 API가 없다(실측 404).
   잘못 만든 업무는 사람이 화면에서 지워야 한다. 그래서 읽은 내용을 보여주고
   확인을 받는 기존 흐름(intake)을 그대로 태운다.
"""
import logging
import re
from dataclasses import dataclass

from .extractor import extract_request_type

log = logging.getLogger(__name__)

LOOKUP = "lookup"
REQUEST = "request"

SYSTEM_PROMPT = """너는 사내 기술지원 접수 창구다. 직원이 대화방에 쓴 한 문장을 읽고,
그것이 **고객정보 조회**인지 **기술지원 요청**인지 판정한다.

- lookup  : 고객 정보를 알고 싶다. "계약 언제 끝나지", "담당자 누구야", 고객번호만 덩그러니
- request : 무언가 해달라는 것. 이전·설치·교체·장애·회수·업그레이드 등

request 라면 아래를 함께 뽑는다. 없으면 null 을 넣는다. 지어내지 마라.
  request_type : 아래 중 하나만.
      장비/설비 이전, 신규설치, 노후교체, SW 업그레이드, 장애, 회수,
      시험아이디 발급, 전환, 해지, 청구변경, 세금계산서
  desired : 희망 일시를 원문 표현 그대로. "9월 30일 오후", "다음주 화요일"
  contact : 연락처나 담당자. 원문에 있는 것만.
  memo    : 원문에 적힌 세부 사항만 한 문장으로.
            ⚠️ 고객번호나 요청 유형을 되풀이해 문장을 지어내지 마라.
               "E120452의 장비/설비 이전" 같은 것은 새 정보가 없으므로 null 이다.
               적을 것이 없으면 null.

애매하면 lookup 이다. 요청으로 잘못 보면 엉뚱한 업무가 생긴다."""

OUTPUT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": [LOOKUP, REQUEST]},
            "request_type": {"type": ["string", "null"]},
            "desired": {"type": ["string", "null"]},
            "contact": {"type": ["string", "null"]},
            "memo": {"type": ["string", "null"]},
        },
        "required": ["kind", "request_type", "desired", "contact", "memo"],
        "additionalProperties": False,
    },
}


@dataclass
class Intent:
    """한 문장의 해석 결과."""
    kind: str = LOOKUP
    request_type: str | None = None
    desired: str | None = None
    contact: str | None = None
    memo: str | None = None

    @property
    def is_request(self) -> bool:
        return self.kind == REQUEST


# 요청 유형 키워드로는 안 잡히는 요청 어투.
#
# "단말이 안 켜져요. 급합니다" 는 명백한 장애 신고인데 REQUEST_TYPES 의
# 장애 키워드(장애·오류·에러·먹통·안됩니다) 어디에도 걸리지 않는다(실측).
# 키워드를 계속 늘리는 것은 끝이 없으므로 **어투**를 함께 본다.
_ASKING = re.compile(
    r"부탁|요청|해\s*주|해\s*줘|주세요|주시|필요|급하|급함|"
    r"안\s*(?:켜|되|돼|나와|먹|잡|열|들어)|고장|망가|바꿔|바꾸|옮기|옮겨|"
    r"해야\s*(?:하|되)|하려는데|하고\s*싶"
)


def might_be_request(text: str) -> bool:
    """LLM에게 물어볼 가치가 있는 문장인가.

    ⚠️ 여기서는 **넓게** 잡고 좁히는 일은 LLM에게 맡긴다. 이 관문의 목적은
       정확한 판정이 아니라 '명백히 요청이 아닌 것'을 걸러 호출을 줄이는 것뿐이다.
       좁게 잡으면 진짜 요청을 놓치는데(위 실측), 그건 되돌릴 방법이 없다.
       넓게 잡아 생긴 오탐은 LLM이 lookup 으로 눕혀 조회가 된다.

    고객번호만 덩그러니 있거나 "담당자 누구야" 같은 문장은 여전히 걸러진다.
    """
    if not text:
        return False
    return extract_request_type(text) is not None or bool(_ASKING.search(text))


def _clean(value) -> str | None:
    """빈 문자열·공백·'null' 문자열을 None 으로 눕힌다."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("null", "none", "미상", "없음"):
        return None
    return text


def parse_intent(raw: dict | None) -> Intent:
    """LLM 응답 → Intent. 이상하면 조회로 눕힌다.

    잘못 읽어 요청이 되는 것보다 조회가 되는 편이 낫다 — 조회는 카드 한 장이지만
    요청은 업무를 만든다.
    """
    if not isinstance(raw, dict):
        return Intent()

    kind = str(raw.get("kind") or "").strip().lower()
    if kind != REQUEST:
        return Intent()

    request_type = _clean(raw.get("request_type"))
    return Intent(
        kind=REQUEST,
        request_type=request_type,
        desired=_clean(raw.get("desired")),
        contact=_clean(raw.get("contact")),
        memo=_clean(raw.get("memo")),
    )


def to_form_text(intent: Intent, code: str, title: str = "요청서") -> str:
    """Intent + 고객번호 → 양식 본문.

    사람이 #이전 으로 받아 손으로 채운 것과 **같은 모양**을 만든다. 그래야
    intake.prepare() 가 그대로 읽고, 확인 화면도 같은 형식으로 나온다.
    고객명은 비워 둔다 — CRM 조회가 채우는 편이 정확하다.
    """
    lines = [
        title,
        "[기본정보]",
        f"고객번호 : {code}",
        "고객명 : ",
        "[요청정보]",
        f"희망일시 : {intent.desired or ''}",
        f"연락처 : {intent.contact or ''}",
        f"메모 : {intent.memo or ''}",
    ]
    return "\n".join(lines)


def form_title(request_type: str | None) -> str:
    """요청 유형 → 양식 제목. 모르는 유형이면 일반 제목."""
    from .form import FORMS
    for title, rtype in FORMS.values():
        if rtype == request_type:
            return title
    return "기술지원요청서"

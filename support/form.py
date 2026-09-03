"""요청서 양식 — 빈 양식 배포와 채워진 양식 해석.

자유 서술로 접수하는 경로(service.py)와 목적이 다르다. 저쪽은 사람이 쓰던 대로
쓰게 두고 AI가 알아서 읽는 쪽이고, 이쪽은 **빠뜨리기 쉬운 항목을 미리 물어보는**
쪽이다. 전화로 요청을 받아 적을 때는 양식이 있는 편이 낫다.

    사용자  #이전
    봇      이전요청서
            [기본정보]
            고객번호 :
            ...

    사용자  #기술정보
            (채운 양식)
    봇      아래 내용으로 업무를 생성할까요?  → #확인 / #취소

⚠️ 확인을 버튼으로 하지 못한다. 일반 메시지의 버튼은 **그려지기만 하고 클릭이
   전달되지 않는다**(2026-09-03 실측: 진짜 업무를 바꾸는 값을 실어 눌러도 상태가
   그대로였다). 개인 토큰으로 보낸 메시지의 버튼이 어느 앱 것인지 Dooray가 알
   방법이 없기 때문이다. 버튼이 실제로 동작하는 곳은 슬래시 커맨드 응답뿐이다
   (support/command.py). 그래서 여기서는 #확인 / #취소 로 받는다.
"""
import datetime as _dt
import re
from dataclasses import dataclass

from crm.parser import parse_all_customer_codes

from .extractor import SupportRequest, extract_desired_date

# 트리거 → (양식 제목, 요청 유형)
# 요청 유형은 extractor.REQUEST_TYPES 의 라벨과 같아야 티켓 제목이 일관된다.
FORMS: dict[str, tuple[str, str]] = {
    "이전": ("이전요청서", "장비/설비 이전"),
    "신규": ("신규설치요청서", "신규설치"),
    "교체": ("노후교체요청서", "노후교체"),
    "장애": ("장애신고서", "장애"),
    "업그레이드": ("SW업그레이드요청서", "SW 업그레이드"),
    "회수": ("회수요청서", "회수"),
}

SUBMIT = "기술정보"      # 채운 양식 제출
CONFIRM = "확인"
CANCEL = "취소"
LIST = "양식"

# 양식 항목. (라벨, 필드명) — 순서가 곧 출력 순서다.
FIELDS = [
    ("[기본정보]", None),
    ("고객번호", "code"),
    ("고객명", "customer_name"),
    ("[요청정보]", None),
    ("희망일시", "desired"),
    ("연락처", "contact"),
    ("메모", "memo"),
]

_LABELS = {label for label, key in FIELDS if key}
_LINE = re.compile(r"^\s*(?P<label>[^:：\[\]]+?)\s*[:：]\s*(?P<value>.*)$")


def parse_command(text: str) -> tuple[str, str] | None:
    """메시지 → (명령, 나머지 본문). '#'으로 시작하지 않으면 None.

    첫 줄의 '#명령'만 본다. 나머지 줄은 양식 본문으로 넘긴다.
    """
    if not text:
        return None
    head, _, rest = text.strip().partition("\n")
    head = head.strip()
    if not head.startswith("#"):
        return None
    return head[1:].strip(), rest.strip()


def build_form(key: str) -> str | None:
    """빈 양식. 모르는 트리거면 None."""
    spec = FORMS.get(key)
    if not spec:
        return None
    title, _ = spec
    lines = [title]
    for label, field in FIELDS:
        lines.append(label if field is None else f"{label} : ")
    return "\n".join(lines)


def build_list() -> str:
    """쓸 수 있는 양식 안내."""
    lines = ["요청서 양식은 아래처럼 부르면 나옵니다."]
    lines += [f"  #{k}   {title}" for k, (title, _) in FORMS.items()]
    lines.append("")
    lines.append(f"채운 뒤에는 #{SUBMIT} 아래에 붙여 주세요.")
    return "\n".join(lines)


@dataclass
class FormData:
    """채워진 양식 1건."""
    request_type: str | None = None
    code: str | None = None
    customer_name: str | None = None
    desired: str | None = None
    contact: str | None = None
    memo: str | None = None
    raw_text: str = ""

    @property
    def is_valid(self) -> bool:
        """고객번호가 없으면 어느 고객 건인지 특정할 수 없다."""
        return bool(self.code)


def _type_from_title(text: str) -> str | None:
    """양식 제목 줄에서 요청 유형을 읽는다."""
    for title, request_type in FORMS.values():
        if title in text:
            return request_type
    return None


def parse_form(text: str) -> FormData:
    """채워진 양식 → FormData.

    사람이 붙여넣는 것이라 공백·빈 줄·라벨 표기가 흔들린다. 아는 라벨만 줍고
    나머지 줄은 버린다. 값이 비면 항목이 없는 것으로 본다.
    """
    data = FormData(raw_text=(text or "").strip())
    data.request_type = _type_from_title(text or "")

    found: dict[str, str] = {}
    for line in (text or "").splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        label = m.group("label").strip()
        if label not in _LABELS:
            continue
        value = m.group("value").strip()
        if value:
            found[label] = value

    for label, field in FIELDS:
        if field and label in found:
            setattr(data, field, found[label])

    # 고객번호 칸이 비었거나 잡담이 섞였어도 본문 어딘가의 E-code를 줍는다
    if not data.code:
        codes = parse_all_customer_codes(text or "")
        data.code = codes[0] if codes else None
    else:
        codes = parse_all_customer_codes(data.code)
        data.code = codes[0] if codes else data.code

    return data


def to_request(data: FormData, today: _dt.date | None = None) -> SupportRequest:
    """FormData → 자유 서술 경로와 같은 SupportRequest.

    이렇게 맞춰 두면 제목·본문 조립(ticket.py)을 그대로 쓴다.
    """
    date, raw = extract_desired_date(data.desired or "", today)
    return SupportRequest(
        customer_codes=[data.code] if data.code else [],
        request_type=data.request_type,
        desired_date=date,
        desired_raw=(data.desired or raw or None),
        raw_text=data.raw_text,
    )


def build_preview(data: FormData, subject: str, customer_name: str | None) -> str:
    """생성 직전 확인 화면.

    파싱이 어긋났으면 여기서 잡으라고 **우리가 읽은 대로** 보여준다.
    """
    rows = [
        ("제목", subject),
        ("고객번호", data.code),
        ("고객명", customer_name or data.customer_name),
        ("희망일시", data.desired),
        ("연락처", data.contact),
        ("메모", data.memo),
    ]
    lines = ["아래 내용으로 업무를 생성할까요?", ""]
    lines += [f"{label} : {value}" for label, value in rows if value]
    lines += ["", f"생성 #{CONFIRM}    취소 #{CANCEL}"]
    return "\n".join(lines)


# ── 대화방 로그에서 양식 찾기 ────────────────────────────────
#
# 슬래시 커맨드에는 여러 줄을 실을 수 없다(2026-09-03 실측: 개행이 들어가면
# 커맨드로 인식되지 않고 일반 메시지로 전송된다). 그래서 양식은 일반 메시지로
# 올리고, 커맨드는 **그 메시지를 찾아 읽는다**. 버튼이 동작하는 곳은 커맨드
# 응답뿐이므로(support/command.py) 확인 버튼을 쓰려면 이 우회가 필요하다.

def looks_like_form(text: str) -> bool:
    """양식으로 볼 만한 메시지인가.

    제목 줄이 있거나 우리 항목 라벨이 두 개 이상 보이면 양식으로 본다.
    사람이 제목 줄을 지우고 붙여넣는 경우가 있어 제목만으로 판정하지 않는다.
    """
    if not text:
        return False
    if _type_from_title(text):
        return True
    hits = sum(1 for label in _LABELS if f"{label} " in text or f"{label}:" in text)
    return hits >= 2


def pick_form(messages: list[dict], user_id: str | None = None) -> str | None:
    """대화방 로그 → 그 사람이 마지막으로 올린 양식 본문. 없으면 None.

    messages 는 Dooray 로그 응답 그대로다(최신이 앞). '#기술정보' 같은 명령
    줄이 앞에 붙어 있으면 떼어 낸다.
    """
    for m in messages or []:
        sender = ((m.get("sender") or {}).get("member") or {}).get("organizationMemberId")
        if user_id and sender != user_id:
            continue
        text = m.get("text") or ""
        parsed = parse_command(text)
        body = parsed[1] if parsed else text
        if looks_like_form(body):
            return body
    return None

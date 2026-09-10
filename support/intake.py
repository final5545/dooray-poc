"""요청서 접수 창구 — '#' 명령 한 줄로 도는 대화 흐름.

    #이전        빈 양식을 받는다
    #기술정보    채운 양식을 낸다 → 우리가 읽은 대로 보여주고 확인을 묻는다
    #확인        업무를 만든다
    #취소        버린다

확인을 버튼으로 하지 못하는 이유는 form.py 머리말 참조. 대신 대기 상태를
프로세스 안에 잠시 들고 있다가 다음 명령을 기다린다.

⚠️ 대기는 **(대화방, 사람)별로** 따로 둔다. 한 방에서 두 사람이 동시에 양식을
   내도 서로의 것을 확정해 버리지 않는다.
"""
import datetime as _dt
import logging
import re
import threading
import time
from dataclasses import dataclass

from crm.client import CrmUnavailable, CustomerRepository
from crm.parser import parse_all_customer_codes

from .form import (
    CANCEL,
    CONFIRM,
    FORMS,
    LIST,
    SUBMIT,
    FormData,
    build_form,
    build_list,
    build_preview,
    parse_command,
    parse_form,
    to_request,
)
from .intent import form_title, might_be_request, to_form_text
from .llm import LLMExtractor
from .repository import TicketRepository
from .ticket import build_body, build_title

log = logging.getLogger(__name__)

# 확인을 기다리는 시간. 넘기면 조용히 버린다 — 한참 뒤의 '#확인'이
# 엉뚱한 양식을 만들어 내지 않게.
PENDING_TTL = 600.0


@dataclass
class Pending:
    data: FormData
    subject: str
    body: str
    at: float
    customer_name: str | None = None


class PendingStore:
    """확인 대기 중인 양식. 프로세스 메모리에만 둔다.

    재시작하면 사라지는데, 사람이 바로 앞에서 확인하는 흐름이라 그래도 된다.
    영속화하면 두 프로세스가 상태를 나눠 가져야 해 비용이 훨씬 크다.
    """

    def __init__(self, ttl: float = PENDING_TTL):
        self._ttl = ttl
        self._items: dict[tuple[str, str], Pending] = {}
        self._lock = threading.Lock()

    def put(self, channel: str, user: str, item: Pending) -> None:
        with self._lock:
            self._items[(channel, user)] = item

    def take(self, channel: str, user: str) -> Pending | None:
        """꺼내면서 지운다. 만료됐으면 None."""
        with self._lock:
            item = self._items.pop((channel, user), None)
        if item is None or (time.time() - item.at) > self._ttl:
            return None
        return item

    def drop(self, channel: str, user: str) -> bool:
        with self._lock:
            return self._items.pop((channel, user), None) is not None

    def waiting(self, channel: str, user: str) -> bool:
        """확인을 기다리는 중인가. 만료된 것은 아니라고 본다."""
        with self._lock:
            item = self._items.get((channel, user))
        return item is not None and (time.time() - item.at) <= self._ttl


# 확인을 기다리는 동안에는 짧은 대답을 그대로 알아듣는다.
#
# 2026-09-10 회의: "해시·슬래시 명령과 다단계 양식은 사용성이 떨어지므로
# 자연어 요청과 1회 확인 중심으로 단순화". #확인 을 외우게 하는 대신
# 사람이 실제로 쓰는 말을 받는다.
#
# ⚠️ **대기 중일 때만** 이 판정을 한다. 평소의 "네"는 그냥 대화다.
_YES = re.compile(
    r"^\s*(네+|넵|예+|응+|ㅇㅇ+|어+|그래+|좋아+|좋|"
    r"맞아+|맞|생성|등록|진행|확인|해|부탁|"
    r"ok|okay|yes|yep|y|go)"
    r"(요|용|여|아요|습니다|하자|주세요|주십시오|줘|줄래|드려요|드립니다|해|시죠)*"
    r"\s*[.!~ㅋㅎ]*\s*$", re.IGNORECASE)
_NO = re.compile(
    r"^\s*(아니+|아뇨|안+돼+|안+되|하지\s*마|취소|말아|말|빼|"
    r"no|nope|n|cancel)"
    r"(요|용|여|에요|예요|입니다|자|줘|주세요|해)*"
    r"\s*[.!~]*\s*$", re.IGNORECASE)


def read_answer(text: str) -> str | None:
    """짧은 대답 → 'yes' | 'no'. 대답이 아니면 None."""
    if not text:
        return None
    if _YES.match(text):
        return "yes"
    if _NO.match(text):
        return "no"
    return None


def handle(text: str, *,
           channel: str,
           user_id: str,
           store: PendingStore,
           tickets: TicketRepository | None = None,
           customers: CustomerRepository | None = None,
           llm: LLMExtractor | None = None,
           origin_message: str | None = None,
           today: _dt.date | None = None,
           on_created=None,
           announce=None) -> str | None:
    """'#' 명령 1건 처리. 우리 명령이 아니면 None(호출자가 평소대로 처리).

    None을 돌려주는 것이 중요하다 — CRM 조회 방의 일반 메시지를 삼키면 안 된다.

    announce: 접수 사실을 기술 지원 방에 알리는 콜백. (제목, 링크)로 부른다.
        여기(CRM 조회 방)에서 낸 요청을 기술팀이 모르고 지나치면 안 된다.
    """
    # 확인을 기다리는 중이면 짧은 대답을 먼저 본다. "네" 한 마디로 끝난다.
    if store.waiting(channel, user_id):
        answer = read_answer(text)
        if answer == "yes":
            return _confirm(channel, user_id, store, tickets, on_created, announce)
        if answer == "no":
            store.drop(channel, user_id)
            return "요청을 취소했습니다."

    parsed = parse_command(text)
    if not parsed:
        return None
    command, rest = parsed

    if command == LIST:
        return build_list()

    if command in FORMS:
        return build_form(command)

    if command == CANCEL:
        return "요청을 취소했습니다." if store.drop(channel, user_id) \
            else "취소할 요청이 없습니다."

    if command == CONFIRM:
        return _confirm(channel, user_id, store, tickets, on_created, announce)

    if command == SUBMIT:
        return _submit(rest, channel=channel, user_id=user_id, store=store,
                       tickets=tickets, customers=customers, llm=llm,
                       origin_message=origin_message, today=today)

    return None          # 우리가 아는 명령이 아니다


def prepare(form_text: str, *, channel: str, user_id: str,
            tickets=None, customers=None, origin_message=None,
            today: _dt.date | None = None) -> tuple[Pending | None, str]:
    """채운 양식 → (대기 항목, 안내문). 만들지는 않는다.

    대기 항목이 None이면 안내문이 곧 오류 사유다. 텍스트 확인(#확인)과 버튼
    확인(슬래시 커맨드) 두 경로가 이 조립을 나눠 쓴다.
    """
    if not (form_text or "").strip():
        return None, (f"#{SUBMIT} 아래에 채운 양식을 붙여 주세요.\n"
                      f"빈 양식이 필요하면 #{LIST} 을 입력하세요.")

    data = parse_form(form_text)
    if not data.is_valid:
        return None, ("고객번호를 찾지 못했습니다.\n"
                      "양식의 '고객번호' 칸에 E로 시작하는 번호를 넣어 주세요.")
    if tickets is None:
        return None, "업무 등록 설정이 없습니다."

    req = to_request(data, today)

    # 고객사명은 CRM 조회가 1순위, 양식에 적힌 값이 폴백이다.
    # 사람이 적은 고객명에는 부서·담당자가 섞여 있어 제목으로 쓰기엔 길다.
    customer_name = None
    if customers is not None and data.code:
        try:
            row = customers.fetch(data.code)
            customer_name = (row or {}).get("name")
        except CrmUnavailable as e:
            # 예상된 상황이다. 커맨드 서버(ai-node)는 사내 CRM 대역에 닿지
            # 못해 매번 여기로 온다(2026-09-10 확인). 스택을 찍을 이유가 없다 —
            # 양식에 적힌 고객명으로 넘어가면 그만이다.
            log.info("CRM 조회 건너뜀 (%s) — 양식의 고객명을 쓴다: %s", e, data.code)
        except Exception:
            log.exception("CRM 조회 실패: %s", data.code)
    if not customer_name:
        customer_name = data.customer_name

    subject = build_title(req, customer_name)
    body = build_body(req, customer_name,
                      detail=data.memo, contact=data.contact,
                      origin_channel=channel, origin_message=origin_message,
                      origin_requester=user_id)

    item = Pending(data=data, subject=subject, body=body, at=time.time(),
                   customer_name=customer_name)
    return item, build_preview(data, subject, customer_name)


def handle_natural(text: str, *, channel: str, user_id: str, store: PendingStore,
                   tickets=None, customers=None, llm=None,
                   origin_message: str | None = None,
                   today: _dt.date | None = None) -> str | None:
    """'#' 없이 말하듯 쓴 요청 → 확인 화면. 요청이 아니면 None.

        "E230096 이전 요청할래"
          → 이전요청서를 대신 채워 확인 화면을 띄운다

    None 을 돌려주면 호출자가 평소대로 고객정보 조회로 넘어간다. 조회 메시지를
    삼키면 안 되므로 **확신이 없을 때는 항상 None** 이다.

    LLM이 없거나 실패해도 None 이다. 그러면 지금까지처럼 조회만 되고, 요청은
    #이전 → #기술정보 로 하면 된다. 기능이 하나 줄 뿐 망가지지는 않는다.
    """
    codes = parse_all_customer_codes(text or "")
    if not codes or tickets is None or llm is None:
        return None

    # 규칙이 먼저다. 요청 유형 키워드가 없으면 LLM을 부르지 않는다 —
    # 평범한 조회에 매번 API를 두드릴 이유가 없다.
    if not might_be_request(text):
        return None

    classify = getattr(llm, "classify", None)
    if not callable(classify):
        return None
    try:
        intent = classify(text)
    except Exception:
        log.exception("의도 분류 실패 — 조회로 넘긴다")
        return None
    if not intent.is_request:
        return None

    # 사람이 손으로 채운 것과 같은 모양을 만들어 같은 경로로 흘린다
    form_text = to_form_text(intent, codes[0], form_title(intent.request_type))
    item, message = prepare(form_text, channel=channel, user_id=user_id,
                            tickets=tickets, customers=customers,
                            origin_message=origin_message, today=today)
    if item is None:
        return None                 # 조립 실패 — 조회로 넘긴다
    store.put(channel, user_id, item)
    log.info("자연어 접수: %s", item.subject)
    return message


def _submit(rest: str, *, channel, user_id, store, tickets, customers, llm,
            origin_message, today) -> str:
    """채운 양식 → 확인 요청(텍스트). 아직 만들지 않는다."""
    item, message = prepare(rest, channel=channel, user_id=user_id,
                            tickets=tickets, customers=customers,
                            origin_message=origin_message, today=today)
    if item is None:
        return message
    store.put(channel, user_id, item)
    return message


def _confirm(channel, user_id, store, tickets, on_created, announce=None) -> str:
    """대기 중인 양식을 업무로 만든다."""
    item = store.take(channel, user_id)
    if item is None:
        return f"확인할 요청이 없습니다. #{SUBMIT} 으로 양식을 먼저 내주세요."
    return create(item, tickets, on_created=on_created, announce=announce)


def create(item: Pending, tickets, *, on_created=None, announce=None) -> str:
    """대기 항목 → 업무. 두 확인 경로가 나눠 쓴다."""
    if tickets is None:
        return "업무 등록 설정이 없습니다."

    try:
        post_id = tickets.create(item.subject, item.body)
    except Exception:
        log.exception("티켓 생성 실패")
        return "요청 등록 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."

    log.info("티켓 등록(양식): %s (%s)", item.subject, post_id)

    # 첫 폴링 전에 완료되면 통보가 누락된다 — 자유 서술 경로와 같은 이유.
    if on_created and post_id:
        try:
            on_created(post_id)
        except Exception:
            log.exception("생성 알림 콜백 실패")

    task_url = None
    url = getattr(tickets, "task_url", None)
    if callable(url) and post_id:
        try:
            task_url = url(post_id)
        except Exception:
            pass

    # 여기서 낸 요청을 기술팀이 모르고 지나치면 안 된다.
    if announce:
        try:
            announce(item.subject, task_url)
        except Exception:
            log.exception("기술 지원 방 알림 실패")

    lines = ["기술지원 요청이 접수되었습니다.", item.subject,
             f"고객번호 : {item.data.code}"]
    if task_url:
        lines.append(task_url)
    return "\n".join(lines)

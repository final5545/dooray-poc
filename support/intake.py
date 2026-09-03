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
import threading
import time
from dataclasses import dataclass

from crm.client import CustomerRepository

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
from .llm import LLMExtractor
from .repository import TicketRepository
from .ticket import build_body, build_title

log = logging.getLogger(__name__)

# 확인을 기다리는 시간. 넘기면 조용히 버린다 — 한참 뒤의 '#확인'이
# 엉뚱한 양식을 만들어 내지 않게.
PENDING_TTL = 600.0


@dataclass
class _Pending:
    data: FormData
    subject: str
    body: str
    at: float


class PendingStore:
    """확인 대기 중인 양식. 프로세스 메모리에만 둔다.

    재시작하면 사라지는데, 사람이 바로 앞에서 확인하는 흐름이라 그래도 된다.
    영속화하면 두 프로세스가 상태를 나눠 가져야 해 비용이 훨씬 크다.
    """

    def __init__(self, ttl: float = PENDING_TTL):
        self._ttl = ttl
        self._items: dict[tuple[str, str], _Pending] = {}
        self._lock = threading.Lock()

    def put(self, channel: str, user: str, item: _Pending) -> None:
        with self._lock:
            self._items[(channel, user)] = item

    def take(self, channel: str, user: str) -> _Pending | None:
        """꺼내면서 지운다. 만료됐으면 None."""
        with self._lock:
            item = self._items.pop((channel, user), None)
        if item is None or (time.time() - item.at) > self._ttl:
            return None
        return item

    def drop(self, channel: str, user: str) -> bool:
        with self._lock:
            return self._items.pop((channel, user), None) is not None


def handle(text: str, *,
           channel: str,
           user_id: str,
           store: PendingStore,
           tickets: TicketRepository | None = None,
           customers: CustomerRepository | None = None,
           llm: LLMExtractor | None = None,
           origin_message: str | None = None,
           today: _dt.date | None = None,
           on_created=None) -> str | None:
    """'#' 명령 1건 처리. 우리 명령이 아니면 None(호출자가 평소대로 처리).

    None을 돌려주는 것이 중요하다 — CRM 조회 방의 일반 메시지를 삼키면 안 된다.
    """
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
        return _confirm(channel, user_id, store, tickets, on_created)

    if command == SUBMIT:
        return _submit(rest, channel=channel, user_id=user_id, store=store,
                       tickets=tickets, customers=customers, llm=llm,
                       origin_message=origin_message, today=today)

    return None          # 우리가 아는 명령이 아니다


def _submit(rest: str, *, channel, user_id, store, tickets, customers, llm,
            origin_message, today) -> str:
    """채운 양식 → 확인 요청. 아직 만들지 않는다."""
    if not rest.strip():
        return (f"#{SUBMIT} 아래에 채운 양식을 붙여 주세요.\n"
                f"빈 양식이 필요하면 #{LIST} 을 입력하세요.")

    data = parse_form(rest)
    if not data.is_valid:
        return ("고객번호를 찾지 못했습니다.\n"
                "양식의 '고객번호' 칸에 E로 시작하는 번호를 넣어 주세요.")
    if tickets is None:
        return "업무 등록 설정이 없습니다."

    req = to_request(data, today)

    # 고객사명은 CRM 조회가 1순위, 양식에 적힌 값이 폴백이다.
    # 사람이 적은 고객명에는 부서·담당자가 섞여 있어 제목으로 쓰기엔 길다.
    customer_name = None
    if customers is not None and data.code:
        try:
            row = customers.fetch(data.code)
            customer_name = (row or {}).get("name")
        except Exception:
            log.exception("CRM 조회 실패: %s", data.code)
    if not customer_name:
        customer_name = data.customer_name

    subject = build_title(req, customer_name)
    body = build_body(req, customer_name,
                      detail=data.memo, contact=data.contact,
                      origin_channel=channel, origin_message=origin_message,
                      origin_requester=user_id)

    store.put(channel, user_id, _Pending(data=data, subject=subject,
                                         body=body, at=time.time()))
    return build_preview(data, subject, customer_name)


def _confirm(channel, user_id, store, tickets, on_created) -> str:
    """대기 중인 양식을 업무로 만든다."""
    item = store.take(channel, user_id)
    if item is None:
        return f"확인할 요청이 없습니다. #{SUBMIT} 으로 양식을 먼저 내주세요."
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

    lines = ["기술지원 요청이 접수되었습니다.", item.subject,
             f"고객번호 : {item.data.code}"]
    url = getattr(tickets, "task_url", None)
    if callable(url) and post_id:
        try:
            lines.append(url(post_id))
        except Exception:
            pass
    return "\n".join(lines)

"""기술지원 요청 1건 처리. Dooray 핸들러가 호출하는 진입점.

기획서 §3 플로우의 1~3단계(요청 등록 → AI 분석 → 현황판 생성)를 담당한다.
4단계(담당자 일정 확정)와 5단계(사후 리마인드)는 별도다.

추출은 하이브리드다 — 형식이 고정된 값은 정규식이 확정하고,
자유서술 필드만 LLM이 보강한다(llm.py 참조).
"""
import datetime as _dt
import logging

from crm.client import CustomerRepository

from .extractor import extract
from .llm import Enrichment, LLMExtractor
from .repository import TicketRepository
from .ticket import build_body, build_title

log = logging.getLogger(__name__)


def handle_request(text: str,
                   tickets: TicketRepository,
                   customers: CustomerRepository | None = None,
                   today: _dt.date | None = None,
                   llm: LLMExtractor | None = None,
                   requester_id: str | None = None,
                   cc_requester: bool = False,
                   origin_channel: str | None = None,
                   origin_message: str | None = None,
                   on_created=None) -> str | None:
    """요청문 → 티켓 생성. 대상이 아니면 None.

    None이면 호출자는 아무것도 보내지 않고 메시지를 폐기해야 한다.
    기술팀 대화방의 모든 메시지가 유입되므로 이 조기 반환이 1차 방어선이다.

    requester_id: 요청자의 organizationMemberId(메시지의 senderId).
        본문에 남겨 두었다가 완료됐을 때 그 사람의 Dooray! News로 알린다.
    cc_requester: 요청자를 참조자로도 넣을지. 기본은 넣지 않는다.
        참조는 '등록' 시점에만 알림을 만들고 상태 변경에는 아무 효과가 없어
        (Dooray 기본 동작) 접수 회신과 겹치는 중복 알림만 남는다.
        ⚠️ 작성자는 참조자가 될 수 없다 — 요청자와 봇이 같은 계정이면 무시된다.
    origin_channel / origin_message: 원 요청 메시지의 좌표.
        완료 알림을 받았을 때 이 대화방·메시지에 인용 답장한다.
    on_created: 티켓 생성 직후 postId로 호출된다.
        완료 감지 스냅샷에 즉시 등록해, 첫 폴링 전에 완료된 건이 누락되지 않게 한다.
    """
    req = extract(text, today)
    if not req.is_actionable:
        return None          # 고객번호 없음 → 기술지원 요청으로 보지 않는다

    # --- 자유서술 필드 보강. 실패해도 티켓 생성은 계속한다 ---
    enr = Enrichment()
    if llm is not None:
        try:
            enr = llm.enrich(text, req)
        except Exception:
            log.exception("LLM 보강 실패 — 규칙 기반 결과만 사용")

    # 정규식이 못 잡은 유형만 LLM 값으로 채운다 (정규식 우선)
    if not req.request_type and enr.request_type:
        req.request_type = enr.request_type

    # --- 고객사명: CRM 조회가 1순위, LLM 추출이 폴백 ---
    customer_name = None
    if customers is not None:
        try:
            row = customers.fetch(req.customer_codes[0])
            customer_name = (row or {}).get("name")
        except Exception:
            log.exception("CRM 조회 실패: %s", req.customer_codes[0])
    if not customer_name:
        customer_name = enr.customer_name

    subject = build_title(req, customer_name)
    body = build_body(req, customer_name, detail=enr.detail, contact=enr.contact,
                      origin_channel=origin_channel, origin_message=origin_message,
                      origin_requester=requester_id)

    try:
        post_id = tickets.create(
            subject, body,
            cc=[requester_id] if (cc_requester and requester_id) else None)
    except Exception:
        log.exception("티켓 생성 실패")
        return "요청 등록 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."

    log.info("티켓 등록: %s (%s)", subject, post_id)

    # 첫 폴링 전에 완료되면 '처음 보는데 이미 완료'로 판단돼 통보가 누락된다.
    if on_created and post_id:
        try:
            on_created(post_id)
        except Exception:
            log.exception("생성 알림 콜백 실패")

    lines = ["기술지원 요청이 접수되었습니다.", subject,
             f"고객번호 : {', '.join(req.customer_codes)}"]
    # 요청자를 참조자로 넣지 않으므로(중복 알림 방지) 업무를 직접 열 수 있도록 링크를 준다.
    url = getattr(tickets, "task_url", None)
    if callable(url) and post_id:
        try:
            lines.append(url(post_id))
        except Exception:
            pass
    return "\n".join(lines)

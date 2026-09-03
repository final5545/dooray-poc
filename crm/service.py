"""메시지 1건 → 응답 텍스트. Dooray 핸들러가 호출하는 유일한 진입점."""
import logging

from .client import CrmUnavailable, CustomerRepository
from .formatter import (
    format_customer_card,
    format_error,
    format_not_found,
    format_unavailable,
)
from .parser import parse_customer_code

log = logging.getLogger(__name__)


def handle_message(text: str, repo: CustomerRepository) -> str | None:
    """조회 대상이면 응답 텍스트를, 아니면 None을 반환한다.

    None이면 호출자는 아무것도 보내지 않고 메시지를 폐기해야 한다.
    대화방 전체 메시지가 유입되므로 이 조기 반환이 1차 방어선이다.
    """
    code = parse_customer_code(text)
    if not code:
        return None            # 대상 아님 → 로깅도 하지 않는다

    try:
        row = repo.fetch(code)
    except CrmUnavailable as e:
        # 시스템 문제 — 미등록과 구분해서 알린다
        log.warning("CRM 사용 불가 (%s): %s", code, e)
        return format_unavailable()
    except Exception:
        log.exception("CRM 조회 실패: %s", code)
        return format_error()

    if not row:
        return format_not_found(code)
    return format_customer_card(row)

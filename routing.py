"""채널 → 핸들러 라우팅.

두 기획서의 기능이 같은 트리거(E-code)를 쓰기 때문에 구분이 필요하다.

  CRM 조회   — "Dooray! 전용 봇 채팅방"에서 `고객정보#E230096`
  기술지원   — "기술팀 Dooray! 방"에서 자유 텍스트

프리픽스는 사람이 빠뜨리기 쉽고 기술지원은 애초에 자유서술이 전제라
강제할 수 없다. 채널로 구분하는 편이 확실하고, 화이트리스트가 곧
라우팅 테이블이 되므로 개인정보 대응(06 §2)과 한 구조로 맞는다.
"""

HANDLERS = ("crm", "support")


class RouteConfigError(ValueError):
    """라우팅 설정 오류. 기동 시점에 즉시 실패시킨다."""


def parse_routes(spec: str) -> dict[str, str]:
    """'채널ID:handler,채널ID:handler' → {채널ID: handler}

    빈 값이면 빈 dict를 반환한다(= 모든 메시지 폐기, 안전한 기본값).

    Raises:
        RouteConfigError: 형식 오류 또는 알 수 없는 핸들러.
    """
    routes: dict[str, str] = {}
    for chunk in (spec or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise RouteConfigError(
                f"'{chunk}' — '채널ID:handler' 형식이어야 합니다. "
                f"사용 가능한 handler: {', '.join(HANDLERS)}"
            )
        channel, handler = (p.strip() for p in chunk.split(":", 1))
        if not channel:
            raise RouteConfigError(f"'{chunk}' — 채널 ID가 비어 있습니다.")
        if handler not in HANDLERS:
            raise RouteConfigError(
                f"'{handler}' — 알 수 없는 handler입니다. "
                f"사용 가능: {', '.join(HANDLERS)}"
            )
        if channel in routes and routes[channel] != handler:
            raise RouteConfigError(
                f"채널 {channel} 이 '{routes[channel]}' 와 '{handler}' 에 중복 지정되었습니다."
            )
        routes[channel] = handler
    return routes

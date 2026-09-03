"""메시지 텍스트에서 조회 대상을 추출한다.

Dooray 대화방의 모든 메시지가 유입되므로(06 §2), 여기서 대상이 아니라고
판정되면 호출자는 즉시 폐기해야 한다. 이것이 개인정보 대응의 1차 방어선이다.
"""
import re

# 고객번호(E-code): E + 5~6자리.
#
# ⚠️ 자릿수가 혼재한다. 기술지원 기획서 화면 예시의 실제 값 기준:
#     6자리 — E140605, E200105, E050282, E050102, E050345, E230096
#     5자리 — E21016
#   CRM 기획서 §3도 "예: #E23009"(5자리)로 적고 있으나
#   화면 예시는 E230096(6자리)이다. 양쪽을 모두 받는다.
_E_CODE = re.compile(r"#?\b(E\d{5,6})\b", re.IGNORECASE)

# 조회 명령 프리픽스. 화면 예시는 "고객정보#E230096" 형태.
# 프리픽스 없이 코드만 있어도 받되, 운영에서 오탐이 많으면
# require_prefix=True로 좁힐 수 있게 해 둔다.
_PREFIX = re.compile(r"고객\s*정보", re.IGNORECASE)


def has_lookup_prefix(text: str) -> bool:
    """'고객정보' 명령 프리픽스가 있는지."""
    return bool(text) and bool(_PREFIX.search(text))


def parse_customer_code(text: str, require_prefix: bool = False) -> str | None:
    """첫 번째 고객번호를 반환. 없으면 None.

    Args:
        require_prefix: True면 '고객정보' 프리픽스가 있을 때만 추출한다.
    """
    if not text:
        return None
    if require_prefix and not has_lookup_prefix(text):
        return None
    m = _E_CODE.search(text)
    return m.group(1).upper() if m else None


def parse_all_customer_codes(text: str) -> list[str]:
    """중복을 제거한 모든 고객번호를 등장 순서대로 반환.

    기술지원 요청은 한 메시지에 복수 고객번호가 들어온다.
    (예: "E21016, E200105 층내 이전 요청" / "E050282, E050102, E050345")
    """
    if not text:
        return []
    seen: dict[str, None] = {}
    for m in _E_CODE.finditer(text):
        seen.setdefault(m.group(1).upper(), None)
    return list(seen)

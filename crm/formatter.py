"""조회 결과를 메신저 출력 텍스트로 조립한다.

형식은 CRM 기획서 §5 화면 출력 예시를 따른다.
  [기본정보]
  고객번호 : E230096
  ...

🔴 출력 규칙 (기획서 §4): CRM 필드가 Null이면 **임의 문자 없이 '공란'으로 표시**.
   → 행을 생략하지 않는다. 라벨은 남기고 값만 비운다.
      "전화2 : " 처럼 비어 있어야 담당자가 '값이 없음'을 인지할 수 있다.

🔴 Dooray 메신저는 마크다운을 거의 지원하지 않는다(06 §7 실측).
   표(|---|), **굵게**, ~~취소선~~ 모두 미렌더링. 인라인 코드만 동작.
   기획서 예시도 순수 텍스트이므로 그대로 따른다.
"""
import os

from .masking import mask_text

# 🔴 마스킹 기본값 — PoC 단계에서는 OFF (2026-09-02 결정).
#
#   기획서 §5 화면 예시가 마스킹 없는 원문 노출이므로 그대로 따른다.
#   단 §1 리스크에 인프라보안팀의 '고객정보 노출 및 침해 우려'와
#   "플랫폼 접목 원천 차단 원칙 고수"가 명시되어 있다.
#   → 운영 전환 전 유관부서 협의 필요. 협의 결과가 '마스킹'이면
#     코드 수정 없이 CRM_MASK=1 로 되돌릴 수 있다.
MASK_BY_DEFAULT = os.getenv("CRM_MASK") == "1"

# (섹션명, [(라벨, 데이터 키), ...])
# 기획서 §4 "CRM 연동 데이터 필드 및 규칙" 기준.
SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("기본정보", [
        ("고객번호", "code"),
        ("고객구분", "customer_type"),   # 계약/무료/시험/청구보류/해지
        ("고객명", "name"),
    ]),
    ("사용자정보", [
        ("부서", "dept"),
        ("이름", "manager"),
        ("전화1", "phone_office"),       # 내선
        ("전화2", "phone_mobile"),       # 모바일
        ("이메일", "email"),
    ]),
    ("계약정보", [
        ("청구일", "billing_date"),
        ("계약시작일", "contract_start"),
        ("계약종료일", "contract_end"),
        ("갱신시작일", "renewal_start"),
    ]),
    ("설치정보", [
        ("설치일자", "install_date"),
        ("기기", "device"),              # 고객/연합
        ("회선구분", "line_type"),        # 고객/ADSL 등
        ("회선구분2", "line_type2"),      # 사내랜/외부회선
        ("통신사", "carrier"),            # SKT/KT/LGU+
    ]),
]

# 마스킹 대상 키. MASK_BY_DEFAULT 또는 mask=True 일 때만 적용된다.
_SENSITIVE = {"phone_office", "phone_mobile", "email"}


def _value(data: dict, key: str, mask: bool) -> str:
    """Null·공백이면 빈 문자열. 임의 문자로 채우지 않는다."""
    raw = data.get(key)
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    return mask_text(text) if (mask and key in _SENSITIVE) else text


def format_customer_card(data: dict, mask: bool | None = None) -> str:
    """CRM 조회 결과 → 메신저 출력 텍스트.

    Args:
        data: CRM 응답 (내부 표준 키).
        mask: 연락처·이메일 마스킹 여부.
              None이면 MASK_BY_DEFAULT(환경변수 CRM_MASK)를 따른다.
    """
    if not data:
        return "조회 결과가 없습니다."

    if mask is None:
        mask = MASK_BY_DEFAULT

    blocks: list[str] = []
    for title, fields in SECTIONS:
        lines = [f"[{title}]"]
        lines += [f"{label} : {_value(data, key, mask)}" for label, key in fields]
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def format_not_found(code: str) -> str:
    """미등록 고객번호 (기획서 §2 '오류' 상태)."""
    return f"등록되지 않은 고객번호입니다 : {code}"


def format_error() -> str:
    """시스템 장애. 내부 오류를 사용자에게 노출하지 않는다(05 §8)."""
    return "조회 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."


def format_unavailable() -> str:
    """CRM 자체를 못 부른 경우. '없는 고객'과 구분해 알린다."""
    return "지금은 고객정보를 조회할 수 없습니다. 잠시 후 다시 시도해 주세요."

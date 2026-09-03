"""민감정보 마스킹.

기획서 §5 화면 예시에는 고객사 담당자의 이메일·전화번호가 마스킹 없이 노출된다.
그러나 §1 리스크에 인프라보안팀의 '고객정보 노출 및 침해 우려'가 명시되어 있어,
기본값은 마스킹으로 둔다. 최종 정책은 유관부서 협의 사항.
"""
import re

_EMAIL = re.compile(r"([\w.+-]+)@([\w-]+\.[\w.-]+)")

# 국내 전화번호. 휴대폰(010-1234-5678)과 유선(02-3774-8013, 051-662-2635)을 모두 포함.
#   기획서 필드: 전화1(내선) / 전화2(모바일) → 양쪽 다 마스킹 대상이다.
# 국번이 3~4자리여야 하므로 'YYYY-MM-DD' 같은 날짜와는 충돌하지 않는다.
_PHONE = re.compile(r"\b(0\d{1,2})[-.\s]?(\d{3,4})[-.\s]?(\d{4})\b")


def mask_email(value: str) -> str:
    """로컬파트의 앞 2자만 남긴다. sanghojeong9210@x.com → sa****@x.com"""
    def _sub(m: re.Match) -> str:
        local, domain = m.group(1), m.group(2)
        keep = local[:2] if len(local) > 2 else local[:1]
        return f"{keep}{'*' * 4}@{domain}"
    return _EMAIL.sub(_sub, value or "")


def mask_phone(value: str) -> str:
    """가운데 국번을 가린다. 02-3774-8013 → 02-****-8013"""
    return _PHONE.sub(lambda m: f"{m.group(1)}-****-{m.group(3)}", value or "")


def mask_text(value: str) -> str:
    """이메일·전화번호를 모두 마스킹."""
    return mask_phone(mask_email(value or ""))

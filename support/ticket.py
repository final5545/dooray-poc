"""추출 결과 → Dooray 업무(티켓) 제목·본문 조립.

기획서 §2: "직관적인 타이틀로 티켓을 생성한다 (예: BNK증권 신규설치 [방문예정 8/14])"
기획서 §5: 본문은 [고객사]/[고객 고유 번호(추출)]/[요청 유형]/[세부 사항] 형태.

고객사명은 요청문에서 파싱하지 않고 **고객번호로 CRM을 조회해서** 얻는다.
자유서술에서 회사명을 뽑는 건 오탐이 크고, 어차피 CRM 연동이 이미 있다.
"""
import re

from .extractor import SupportRequest

DEFAULT_STATUS = "접수"     # AI 자동 등록 시점의 상태 (기획서 §4)

# 원 요청의 좌표를 본문에 남긴다.
# 완료 알림(Dooray! News)을 받았을 때 "어느 대화방 어느 메시지에 답할지"를
# 알아야 하는데, Dooray 업무에는 그 정보를 담을 별도 필드가 없다.
#
# requester는 요청자의 organizationMemberId다. 완료됐을 때 그 사람의
# Dooray! News로 알림을 보내는 데 쓴다. 업무의 users.cc에서 읽으면 될 것
# 같지만, Dooray는 **작성자를 참조자로 넣지 못하게** 막는다(2026-09-03 실측:
# 봇이 곧 작성자인 지금 구조에서 cc가 빈 배열로 돌아온다). 그래서 본문에
# 직접 남긴다.
ORIGIN_LINE = "[요청출처] channel={channel} message={message}"
_ORIGIN_RE = re.compile(r"\[요청출처\]\s*channel=(\S+)\s+message=(\S+)")
_REQUESTER_RE = re.compile(r"\[요청출처\][^\n]*?\srequester=(\S+)")


def build_origin_line(channel: str, message: str, requester: str | None = None) -> str:
    line = ORIGIN_LINE.format(channel=channel, message=message)
    return f"{line} requester={requester}" if requester else line


def parse_origin(body: str) -> tuple[str, str] | None:
    """티켓 본문 → (channelId, messageId). 없으면 None."""
    if not body:
        return None
    m = _ORIGIN_RE.search(body)
    return (m.group(1), m.group(2)) if m else None


def parse_requester(body: str) -> str | None:
    """티켓 본문 → 요청자 memberId. 이 줄이 없던 시절의 티켓이면 None."""
    if not body:
        return None
    m = _REQUESTER_RE.search(body)
    return m.group(1) if m else None


def build_title(req: SupportRequest, customer_name: str | None = None,
                status_label: str = DEFAULT_STATUS) -> str:
    """예: 'BNK증권 신규설치 [접수 8/28]'

    기획서 예시의 '[방문예정 8/14]'는 담당자가 일정을 확정한 뒤의 상태다.
    AI 자동 등록 시점은 '접수'이므로 기본값을 그렇게 둔다.
    """
    head = " ".join(p for p in (customer_name, req.request_type) if p)
    if not head:
        head = ", ".join(req.customer_codes) or "기술지원 요청"

    if req.desired_date:
        d = req.desired_date
        return f"{head} [{status_label} {d.month}/{d.day}]"
    return f"{head} [{status_label}]"


def build_body(req: SupportRequest, customer_name: str | None = None,
               detail: str | None = None, contact: str | None = None,
               origin_channel: str | None = None,
               origin_message: str | None = None,
               origin_requester: str | None = None) -> str:
    """기획서 §5 'AI 분석 결과' 형태의 본문.

    detail / contact 는 LLM 보강 결과다(llm.py). 없으면 행을 생략한다.
    origin_* 은 완료 알림 때 회신할 원 요청의 좌표다.
    """
    lines = [
        f"[고객사] {customer_name or ''}",
        f"[고객 고유 번호(추출)] {', '.join(req.customer_codes)}",
        f"[요청 유형] {req.request_type or ''}",
    ]
    if req.desired_raw or req.desired_date:
        when = req.desired_raw or (req.desired_date.isoformat() if req.desired_date else "")
        lines.append(f"[희망일정] {when}")
    if detail:
        lines.append(f"[세부 사항] {detail}")
    if contact:
        lines.append(f"[담당자] {contact}")

    lines += ["", "[원문]", req.raw_text, ""]
    if origin_channel and origin_message:
        lines.append(build_origin_line(origin_channel, origin_message, origin_requester))
    lines.append("— AI 자동 등록 (기술지원 요청 자동화 PoC)")
    return "\n".join(lines)

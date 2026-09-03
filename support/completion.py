"""완료 알림 처리 — Dooray! News 프레임 → 원 요청에 회신할 내용.

기획서 §1의 목표("그거 처리됐나요?" 라는 확인 커뮤니케이션 제거)는
**원래 요청했던 대화 맥락에 답이 달려야** 달성된다.
Dooray 기본 알림은 알림함으로만 가므로 이 계층이 필요하다.

흐름:
    기술담당자가 완료 클릭
      → [Dooray 자동화] 봇을 담당자로 추가
      → Dooray-Bot이 News로 알림
      → 이 모듈이 업무 ID를 뽑아 티켓 본문의 원 요청 좌표를 찾아냄
      → 호출자가 그 대화방·메시지에 인용 답장
"""
import logging
import re
from dataclasses import dataclass

from .notify import NewsEvent, parse_news
from .repository import TicketRepository
from .ticket import parse_origin

log = logging.getLogger(__name__)

CLOSED = "closed"


@dataclass
class CompletionReply:
    """어디에 무엇을 회신할지."""
    channel: str
    message_id: str
    text: str


# 티켓 제목은 "{고객사} {유형} [{상태} {날짜}]" 형태다.
# 완료 통보문에 접수 시점의 상태가 그대로 남으면 혼란스러우므로 떼어낸다.
_STATUS_SUFFIX = re.compile(r"\s*\[[^\]]*\]\s*$")


def _format(actor_name: str | None, subject: str) -> str:
    lines = ["✅ 기술지원 요청이 처리 완료되었습니다."]
    clean = _STATUS_SUFFIX.sub("", subject or "").strip()
    if clean:
        lines.append(clean)
    if actor_name:
        lines.append(f"처리자 : {actor_name}")
    return "\n".join(lines)


def reply_for_task(task: dict, actor_name: str | None = None) -> CompletionReply | None:
    """업무 상세 → 회신 지시. 통보 대상이 아니면 None.

    News 알림 경로와 폴링 경로가 공유하는 판정 로직이다.

    None인 경우:
      - 완료(closed) 상태가 아님
      - 우리 봇이 만든 티켓이 아님 (본문에 원 요청 좌표가 없음)
    """
    if not task or task.get("workflowClass") != CLOSED:
        return None

    body = ((task.get("body") or {}).get("content")) or ""
    origin = parse_origin(body)
    if not origin:
        # 사람이 직접 만든 업무 등 — 회신할 곳이 없다
        return None

    channel, message_id = origin
    return CompletionReply(
        channel=channel,
        message_id=message_id,
        text=_format(actor_name, task.get("subject") or ""),
    )


def handle_news(frame: dict, tickets: TicketRepository,
                project_code: str | None = None) -> CompletionReply | None:
    """News 프레임 1건 → 회신 지시. 대상이 아니면 None.

    None인 경우:
      - 업무 알림이 아님 (attachments 없는 create 프레임 포함)
      - **다른 프로젝트 업무** — News에는 참여 중인 모든 프로젝트 알림이 들어온다
      - 완료(closed) 상태가 아님 — 담당자 변경 등 다른 알림
      - 우리가 만든 티켓이 아님 (본문에 원 요청 좌표가 없음)

    project_code: 우리 현황판 프로젝트 코드. 지정하면 다른 프로젝트 알림을 먼저 버린다.
        지정하지 않으면 조회를 시도하다 403이 난다(권한 없는 프로젝트).
    """
    event = parse_news(frame)
    if not event:
        return None

    # 다른 프로젝트 알림은 조회조차 하지 않는다.
    # News에는 참여 중인 전 프로젝트의 알림이 흘러들어오므로 이 필터가 없으면
    # 매번 남의 프로젝트에 조회를 날려 403을 맞는다.
    if project_code and event.project_code and event.project_code != project_code:
        return None

    try:
        task = tickets.get(event.task_id)
    except Exception as e:
        # 권한 없는 프로젝트의 업무는 403이 정상이다. 오류로 시끄럽게 굴지 않는다.
        log.debug("업무 조회 실패(무시): %s (%s)", event.task_id, e)
        return None

    # 완료된 건만 통보한다. 담당자 변경·태그 추가 등 다른 알림도 같은 채널로 온다.
    return reply_for_task(task, event.actor_name)

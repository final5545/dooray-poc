"""Dooray! News 알림 파싱.

실측(2026-09-02): 업무에 사람이 추가되면 Dooray-Bot이 개인 봇 채널로 알림을 보낸다.
그 채널이 곧 Dooray! News이고, **채널 ID가 자기 memberId와 같다**.
일반 대화방 목록(/messenger/v1/channels)에는 나오지 않는다.

프레임 예시:
    content.channelId  = <내 memberId>
    content.customName = "Dooray-Bot"
    content.type       = 2                       # 봇 알림
    content.text       = 'Task [@정시욱](dooray://.../members/3362... "member")'
    content.attachments[0] = {
        "title": "AI-PoC-Agent-Test/12: 알림 테스트",
        "titleLink": "https://infomax.dooray.com/project/tasks/4412603105543031023",
        "text": "TEST "
    }

⚠️ action이 create가 아니라 **update**인 프레임에 attachments가 채워진다.
   create 프레임에는 아직 없다.
"""
import re
from dataclasses import dataclass

BOT_NAME = "Dooray-Bot"
TYPE_BOT_NOTICE = 2

# titleLink 끝의 업무 ID
_TASK_ID = re.compile(r"/project/tasks/(\d+)")
# "프로젝트코드/번호: 제목"
_TITLE = re.compile(r"^(?P<project>[^/]+)/(?P<number>\d+)\s*:\s*(?P<subject>.*)$")
# 'Task [@정시욱](dooray://.../members/3362... "member")'
_ACTOR = re.compile(r"\[@(?P<name>[^\]]+)\]\(dooray://[^/]+/members/(?P<id>\d+)")


@dataclass
class NewsEvent:
    """업무 알림 1건."""
    task_id: str
    project_code: str | None = None
    task_number: str | None = None
    subject: str | None = None
    actor_name: str | None = None
    actor_id: str | None = None
    raw_title: str = ""


def is_news_channel(channel_id: str, my_member_id: str) -> bool:
    """Dooray! News(개인 봇 채널)인가. 채널 ID가 자기 memberId와 같다."""
    return bool(channel_id) and channel_id == my_member_id


def parse_news(frame: dict) -> NewsEvent | None:
    """News 프레임 → NewsEvent. 업무 알림이 아니면 None.

    attachments가 없는 create 프레임은 None을 돌려준다(뒤따르는 update에서 채워진다).
    """
    content = (frame or {}).get("content") or {}
    if content.get("customName") != BOT_NAME:
        return None

    attachments = content.get("attachments") or []
    if not attachments:
        return None                      # 아직 본문이 안 채워진 create 프레임

    att = attachments[0] or {}
    link = att.get("titleLink") or ""
    m = _TASK_ID.search(link)
    if not m:
        return None                      # 업무 알림이 아님 (위키·기타)
    task_id = m.group(1)

    raw_title = att.get("title") or ""
    project = number = subject = None
    tm = _TITLE.match(raw_title.strip())
    if tm:
        project = tm.group("project")
        number = tm.group("number")
        subject = tm.group("subject").strip() or None

    actor_name = actor_id = None
    am = _ACTOR.search(content.get("text") or "")
    if am:
        actor_name = am.group("name")
        actor_id = am.group("id")

    return NewsEvent(
        task_id=task_id,
        project_code=project,
        task_number=number,
        subject=subject,
        actor_name=actor_name,
        actor_id=actor_id,
        raw_title=raw_title,
    )

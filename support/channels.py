"""개인에게 알림을 도달시킬 채널 고르기.

Dooray! News는 개인 봇 채널이고 채널 ID가 곧 그 사람의 memberId다(notify.py).
**자기 News에는 넣을 수 있지만 남의 News에는 못 넣는다** — 그 채널의 멤버가
아니기 때문이다.

    2026-09-03 실측
    POST /messenger/v1/channels/{남의 memberId}/logs
      → 500  CHANNEL_NOT_JOINED_MEMBER_ERROR

Dooray-Bot이 모두의 News에 쓰는 것은 시스템 봇 권한이라 개인 액세스 토큰으로는
흉내 낼 수 없다. 그래서 남에게는 1:1 대화방으로 보낸다(실측 200).
"""

DIRECT = "direct"


def direct_channels(rows: list[dict], me: str) -> dict[str, str]:
    """채널 목록 → {상대 memberId: 1:1 채널 ID}.

    참여자 구조는 실측 기준이다:
        {"type": "direct",
         "users": {"participants": [{"member": {"organizationMemberId": ...}}, ...]}}

    나와의 대화(참여자가 나뿐)는 1:1 상대가 없으므로 자연히 빠진다.
    """
    out: dict[str, str] = {}
    for c in rows or []:
        if c.get("type") != DIRECT or not c.get("id"):
            continue
        for p in (c.get("users") or {}).get("participants") or []:
            mid = (p.get("member") or {}).get("organizationMemberId")
            if mid and mid != me:
                out[mid] = c["id"]
    return out


def me_from_channels(rows: list[dict]) -> str | None:
    """채널 목록 → 내 memberId.

    각 채널 객체에 me.member.organizationMemberId 가 들어 있다(실측). 덕분에
    소켓 토큰을 새로 발급하거나 별도 설정을 두지 않고도 목록 1회로 알 수 있다.
    """
    for c in rows or []:
        mid = ((c.get("me") or {}).get("member") or {}).get("organizationMemberId")
        if mid:
            return mid
    return None


def channel_for_member(member_id: str, me: str, directs: dict[str, str]) -> str | None:
    """그 사람에게 알림을 넣을 채널. 보낼 곳이 없으면 None.

        본인 → Dooray! News (채널 ID == memberId)
        그 외 → 1:1 대화방

    1:1로 대화한 적이 없으면 None이다. 방을 새로 파면서까지 알릴 일은 아니고,
    대화방 인용 답장은 어차피 그대로 간다.
    """
    if not member_id:
        return None
    if member_id == me:
        return member_id
    return directs.get(member_id)

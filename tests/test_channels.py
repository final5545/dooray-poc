"""완료 알림을 개인에게 도달시킬 채널 고르기.

2026-09-03 실측:
    남의 News       → 500 CHANNEL_NOT_JOINED_MEMBER_ERROR   (멤버가 아님)
    내 News         → 200
    1:1 대화방      → 200
"""
from support.channels import (
    channel_for_member,
    direct_channels,
    me_from_channels,
)

ME = "3267267451433100066"        # 정원석
OTHER = "3362258975191542304"     # 정시욱
DM = "3448488509605223992"        # 둘의 1:1 방


def _direct(cid, member_ids):
    return {
        "id": cid, "type": "direct",
        "users": {"participants": [
            {"type": "member", "member": {"organizationMemberId": m}}
            for m in member_ids]},
    }


class TestDirectChannels:
    def test_상대를_키로_1대1_방을_찾는다(self):
        got = direct_channels([_direct(DM, [OTHER, ME])], ME)
        assert got == {OTHER: DM}

    def test_나와의_대화는_상대가_없어_빠진다(self):
        # 참여자가 나뿐인 '나와의 대화'는 1:1 상대가 없다
        assert direct_channels([_direct("self-1", [ME])], ME) == {}

    def test_단체방은_보지_않는다(self):
        rows = [{"id": "g1", "type": "private",
                 "users": {"participants": [
                     {"member": {"organizationMemberId": OTHER}}]}}]
        assert direct_channels(rows, ME) == {}

    def test_참여자_구조가_비어도_깨지지_않는다(self):
        assert direct_channels([{"id": "d1", "type": "direct"}], ME) == {}
        assert direct_channels([{"id": "d1", "type": "direct", "users": {}}], ME) == {}
        assert direct_channels([], ME) == {}
        assert direct_channels(None, ME) == {}

    def test_id_없는_채널은_건너뛴다(self):
        assert direct_channels([_direct(None, [OTHER])], ME) == {}


class TestChannelForMember:
    DIRECTS = {OTHER: DM}

    def test_본인이면_News로_간다(self):
        # News 채널 ID는 곧 자기 memberId다
        assert channel_for_member(ME, ME, self.DIRECTS) == ME

    def test_남이면_1대1_방으로_간다(self):
        # 남의 News에는 못 넣는다 — 그 채널의 멤버가 아니다
        assert channel_for_member(OTHER, ME, self.DIRECTS) == DM

    def test_1대1로_대화한_적_없으면_보낼_곳이_없다(self):
        assert channel_for_member("9999", ME, self.DIRECTS) is None

    def test_요청자를_모르면_보낼_곳이_없다(self):
        assert channel_for_member(None, ME, self.DIRECTS) is None
        assert channel_for_member("", ME, self.DIRECTS) is None


class TestMeFromChannels:
    """채널 목록에 내 memberId가 실려 온다 — 소켓 토큰을 새로 발급할 필요가 없다."""

    def test_me_필드에서_내_ID를_읽는다(self):
        rows = [{"id": "c1", "type": "direct",
                 "me": {"member": {"organizationMemberId": ME}}}]
        assert me_from_channels(rows) == ME

    def test_단체방에서도_읽힌다(self):
        rows = [{"id": "g1", "type": "private",
                 "me": {"member": {"organizationMemberId": ME}}}]
        assert me_from_channels(rows) == ME

    def test_없으면_None(self):
        assert me_from_channels([{"id": "c1", "type": "direct"}]) is None
        assert me_from_channels([]) is None
        assert me_from_channels(None) is None

"""Dooray! News 프레임 파싱 — 2026-09-02 실제 관측 프레임 기준."""
from support.notify import is_news_channel, parse_news

MY_ID = "3267267451433100066"

# 실제 관측된 완료 알림 프레임 (정시욱 사원이 완료 처리)
REAL_FRAME = {
    "version": "5",
    "type": "channelLog",
    "action": "update",
    "content": {
        "id": "4412610222742900012",
        "channelId": MY_ID,
        "type": 2,
        "senderId": "3262462486750041656",
        "customName": "Dooray-Bot",
        "text": 'Task [@정시욱](dooray://3262462484277387103/members/3362258975191542304 "member")',
        "attachments": [{
            "color": "#6a7dd0",
            "title": "AI-PoC-Agent-Test/12: 알림 테스트",
            "titleLink": "https://infomax.dooray.com/project/tasks/4412603105543031023",
            "text": "TEST ",
        }],
    },
    "references": {},
}


class TestNewsChannel:
    def test_채널ID가_내_memberId면_News다(self):
        # 실측: News는 개인 봇 채널이고 채널 ID가 자기 memberId와 같다
        assert is_news_channel(MY_ID, MY_ID)

    def test_다른_채널은_아니다(self):
        assert not is_news_channel("3448488509605223992", MY_ID)

    def test_빈_값(self):
        assert not is_news_channel("", MY_ID)
        assert not is_news_channel(None, MY_ID)


class TestParseNews:
    def test_실제_프레임_파싱(self):
        got = parse_news(REAL_FRAME)
        assert got is not None
        assert got.task_id == "4412603105543031023"
        assert got.project_code == "AI-PoC-Agent-Test"
        assert got.task_number == "12"
        assert got.subject == "알림 테스트"
        assert got.actor_name == "정시욱"
        assert got.actor_id == "3362258975191542304"

    def test_attachments가_없으면_None(self):
        # create 프레임에는 아직 attachments가 없다. 뒤따르는 update에서 채워진다.
        frame = {"content": dict(REAL_FRAME["content"], attachments=[])}
        assert parse_news(frame) is None

    def test_봇이_아니면_None(self):
        frame = {"content": dict(REAL_FRAME["content"], customName="정원석")}
        assert parse_news(frame) is None

    def test_업무_링크가_아니면_None(self):
        att = [{"title": "위키 문서", "titleLink": "https://infomax.dooray.com/wiki/pages/123"}]
        frame = {"content": dict(REAL_FRAME["content"], attachments=att)}
        assert parse_news(frame) is None

    def test_제목_형식이_달라도_업무ID는_뽑는다(self):
        att = [dict(REAL_FRAME["content"]["attachments"][0], title="형식이 다른 제목")]
        frame = {"content": dict(REAL_FRAME["content"], attachments=att)}
        got = parse_news(frame)
        assert got and got.task_id == "4412603105543031023"
        assert got.project_code is None

    def test_처리자_멘션이_없어도_된다(self):
        frame = {"content": dict(REAL_FRAME["content"], text="Task")}
        got = parse_news(frame)
        assert got and got.actor_name is None

    def test_빈_입력(self):
        assert parse_news({}) is None
        assert parse_news(None) is None

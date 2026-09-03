"""완료 시 요청자의 Dooray! News로도 알린다.

두레이는 업무 '상태 변경'에 자동 알림을 주지 않는다. 그래서 자동 알림은
포기하되, News 채널(채널ID == memberId)에 **우리가 직접 넣는** 경로를 쓴다.
2026-09-03 실측으로 HTTP 200과 카드 렌더링을 확인했다.

여기서 지키는 것:
  - 요청자를 알아낼 수 있어야 한다 (본문에 남긴다)
  - 요청자를 모르면 조용히 건너뛴다 (예전 티켓 호환)
  - 대화방 답장과 News는 서로 독립이다
"""
from support.completion import CompletionReply, news_card, reply_for_task
from support.ticket import build_origin_line, parse_origin, parse_requester

CHANNEL = "3267267775953625054"
MESSAGE = "4412681277099085783"
REQUESTER = "3362000000000000000"


class TestOriginLine:
    def test_요청자까지_한_줄에_남긴다(self):
        line = build_origin_line(CHANNEL, MESSAGE, REQUESTER)
        assert parse_origin(line) == (CHANNEL, MESSAGE)
        assert parse_requester(line) == REQUESTER

    def test_요청자가_없어도_좌표는_읽힌다(self):
        line = build_origin_line(CHANNEL, MESSAGE)
        assert parse_origin(line) == (CHANNEL, MESSAGE)
        assert parse_requester(line) is None

    def test_이_줄이_없던_시절의_본문(self):
        # requester= 를 넣기 전에 만들어진 티켓도 그대로 동작해야 한다
        old = f"[요청출처] channel={CHANNEL} message={MESSAGE}\n— AI 자동 등록"
        assert parse_origin(old) == (CHANNEL, MESSAGE)
        assert parse_requester(old) is None

    def test_message_뒤에_붙어도_message를_삼키지_않는다(self):
        line = build_origin_line(CHANNEL, MESSAGE, REQUESTER)
        assert parse_origin(line)[1] == MESSAGE      # requester= 가 섞이면 안 된다


def _task(body_extra: str, state: str = "closed") -> dict:
    return {
        "id": "t-1",
        "subject": "한국거래소 SW 업그레이드 [접수 9/3]",
        "workflowClass": state,
        "body": {"content": f"[원문]\n윈도우 업데이트 부탁드립니다.\n{body_extra}"},
    }


class TestReplyCarriesRequester:
    def test_본문에서_요청자를_찾아_실어_보낸다(self):
        r = reply_for_task(_task(build_origin_line(CHANNEL, MESSAGE, REQUESTER)))
        assert r.requester_id == REQUESTER

    def test_요청자가_없으면_None이지만_회신은_살아있다(self):
        r = reply_for_task(_task(build_origin_line(CHANNEL, MESSAGE)))
        assert r is not None and r.requester_id is None
        assert r.channel == CHANNEL and r.message_id == MESSAGE

    def test_제목에서_접수_상태_꼬리표를_뗀다(self):
        r = reply_for_task(_task(build_origin_line(CHANNEL, MESSAGE, REQUESTER)))
        assert r.subject == "한국거래소 SW 업그레이드"

    def test_업무_링크를_실어_보낸다(self):
        r = reply_for_task(_task(build_origin_line(CHANNEL, MESSAGE, REQUESTER)),
                           task_url="https://infomax.dooray.com/project/tasks/t-1")
        assert r.task_url.endswith("/t-1")


class TestNewsCard:
    def _reply(self, **kw):
        base = dict(channel=CHANNEL, message_id=MESSAGE,
                    text="✅ 기술지원 요청이 처리 완료되었습니다.\n한국거래소 SW 업그레이드",
                    requester_id=REQUESTER, subject="한국거래소 SW 업그레이드",
                    task_url="https://infomax.dooray.com/project/tasks/t-1")
        base.update(kw)
        return CompletionReply(**base)

    def test_요청자를_모르면_보내지_않는다(self):
        assert news_card(self._reply(requester_id=None)) is None

    def test_첫_줄이_알림_제목이_된다(self):
        # News 목록에서는 text만 보이므로 여기에 결론이 와야 한다
        card = news_card(self._reply())
        assert card["text"] == "✅ 기술지원 요청이 처리 완료되었습니다."
        assert "\n" not in card["text"]

    def test_업무_제목과_링크가_카드에_붙는다(self):
        a = news_card(self._reply())["attachments"][0]
        assert a["title"] == "한국거래소 SW 업그레이드"
        assert a["titleLink"].endswith("/t-1")

    def test_링크를_못_만들어도_카드는_보낸다(self):
        a = news_card(self._reply(task_url=None))["attachments"][0]
        assert "titleLink" not in a and a["title"]

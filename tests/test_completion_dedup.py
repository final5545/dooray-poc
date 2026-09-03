"""완료 통보가 두 번 가지 않는다.

버튼으로 완료하면 커맨드 서버가 그 자리에서 봇 공지를 띄운다. 그런데 완료
감지 폴링은 같은 변화를 5분 안에 또 잡아 원 요청에 인용 답장을 단다.
같은 사실이 두 번 알려지면 안 된다.

두 프로세스는 다른 기계에서 돌아 상태를 나눌 수 없다. 공유 매체는 업무
본문뿐이고, 워처는 어차피 본문을 읽으므로(원 요청 좌표를 찾느라) 읽는 쪽
비용이 없다.
"""
from support.completion import reply_for_task
from support.repository import FakeTicketRepository
from support.ticket import build_origin_line, is_notified, mark_notified

CHANNEL, MESSAGE = "ch-1", "msg-1"
ORIGIN = build_origin_line(CHANNEL, MESSAGE, "member-1")


def _task(body: str, state: str = "closed") -> dict:
    return {"id": "t1", "subject": "한국거래소 SW 업그레이드 [접수]",
            "workflowClass": state, "body": {"content": body}}


class TestMark:
    def test_표식을_붙인다(self):
        assert is_notified(mark_notified("본문"))

    def test_두_번_붙이지_않는다(self):
        once = mark_notified("본문")
        assert mark_notified(once) == once

    def test_원래_본문은_남는다(self):
        assert ORIGIN in mark_notified(f"[원문]\n요청합니다\n{ORIGIN}")

    def test_표식이_있어도_원_요청_좌표는_읽힌다(self):
        from support.ticket import parse_origin, parse_requester
        marked = mark_notified(ORIGIN)
        assert parse_origin(marked) == (CHANNEL, MESSAGE)
        assert parse_requester(marked) == "member-1"

    def test_표식_없는_본문(self):
        assert not is_notified("[원문]\n요청합니다")
        assert not is_notified("")
        assert not is_notified(None)


class TestPollingSkips:
    def test_버튼으로_통보된_건은_폴링이_건너뛴다(self):
        assert reply_for_task(_task(mark_notified(ORIGIN))) is None

    def test_표식이_없으면_평소대로_통보한다(self):
        # 두레이 웹에서 직접 완료한 건 — 봇 공지가 없었으므로 폴링이 알려야 한다
        got = reply_for_task(_task(ORIGIN))
        assert got is not None and got.channel == CHANNEL

    def test_표식이_없던_시절의_티켓도_통보된다(self):
        old = f"[요청출처] channel={CHANNEL} message={MESSAGE}"
        assert reply_for_task(_task(old)) is not None


class TestRepositoryMark:
    def _repo(self):
        return FakeTicketRepository({"t1": {"subject": "건", "workflowClass": "closed",
                                            "body": {"content": ORIGIN}}})

    def test_표식을_남기면_폴링이_건너뛴다(self):
        repo = self._repo()
        assert repo.mark_notified("t1") is True
        assert reply_for_task(repo.get("t1")) is None

    def test_이미_표식이_있으면_쓰지_않는다(self):
        repo = self._repo()
        repo.mark_notified("t1")
        assert repo.mark_notified("t1") is False      # 불필요한 API 호출 방지

    def test_없는_업무는_조용히_무시(self):
        assert self._repo().mark_notified("없음") is False

"""생성 직후 완료된 건 누락 방지 — track().

실제로 놓친 사례가 있어 추가한 테스트다.
티켓이 15:29:30에 생성되고 15:29:47 첫 폴링 전에 완료되자,
폴링이 '처음 보는데 이미 완료'로 판단해 통보하지 않았다.
"""
import datetime as dt

import pytest

from crm.client import FakeCustomerRepository
from support.repository import FakeTicketRepository
from support.service import handle_request
from support.ticket import ORIGIN_LINE
from support.watcher import CompletionWatcher, StateStore

ORIGIN_CH = "4412501746823008358"
ORIGIN_MSG = "4412630682117103793"
BODY = "[원문]\n요청\n\n" + ORIGIN_LINE.format(channel=ORIGIN_CH, message=ORIGIN_MSG)


def task(state: str) -> dict:
    return {"subject": "한국거래소 SW 업그레이드 [접수]", "workflowClass": state,
            "body": {"mimeType": "text/x-markdown", "content": BODY}}


@pytest.fixture
def watcher(tmp_path):
    return CompletionWatcher(FakeTicketRepository({}), StateStore(str(tmp_path / "s.json")))


class TestTrack:
    def test_스냅샷에_등록된다(self, tmp_path):
        rows = {"old": task("closed")}
        repo = FakeTicketRepository(rows)
        w = CompletionWatcher(repo, StateStore(str(tmp_path / "s.json")))
        w.poll()                                  # 시딩

        w.track("t-new")
        assert w.state.load()["t-new"] == "registered"

    def test_이미_있는_건은_덮어쓰지_않는다(self, tmp_path):
        rows = {"t1": task("working")}
        repo = FakeTicketRepository(rows)
        w = CompletionWatcher(repo, StateStore(str(tmp_path / "s.json")))
        w.poll()
        w.track("t1")                             # 이미 working
        assert w.state.load()["t1"] == "working"

    def test_스냅샷이_없으면_아무것도_하지_않는다(self, watcher):
        # 첫 폴링 전. 곧 이어질 시딩이 현재 상태를 담는다.
        watcher.track("t1")
        assert watcher.state.load() is None

    def test_빈_ID는_무시(self, tmp_path):
        repo = FakeTicketRepository({"a": task("working")})
        w = CompletionWatcher(repo, StateStore(str(tmp_path / "s.json")))
        w.poll()
        before = dict(w.state.load())
        w.track("")
        w.track(None)
        assert w.state.load() == before


class TestMissedCompletionRegression:
    def test_생성_직후_완료된_건도_통보된다(self, tmp_path):
        """실제로 놓쳤던 시나리오의 회귀 테스트."""
        rows = {"old": task("closed")}
        repo = FakeTicketRepository(rows)
        w = CompletionWatcher(repo, StateStore(str(tmp_path / "s.json")))
        w.poll()                                  # 시딩 (새 티켓은 아직 없음)

        # 티켓 생성 → track() 으로 즉시 등록
        rows["t-new"] = task("registered")
        w.track("t-new")

        # 첫 폴링 전에 완료
        rows["t-new"] = task("closed")

        got = w.poll()
        assert len(got.replies) == 1, "생성 직후 완료된 건을 놓쳤다"
        assert got.replies[0].message_id == ORIGIN_MSG

    def test_track이_없으면_놓친다(self, tmp_path):
        """track() 없이는 어떻게 누락되는지 — 수정 전 동작 고정."""
        rows = {"old": task("closed")}
        repo = FakeTicketRepository(rows)
        w = CompletionWatcher(repo, StateStore(str(tmp_path / "s.json")))
        w.poll()

        rows["t-new"] = task("closed")            # track 없이 이미 완료 상태로 등장
        assert w.poll().replies == []

    def test_폴링이_track한_항목을_지우지_않는다(self, tmp_path):
        # 폴링 조회 시점에 목록에 아직 안 잡힌 티켓이 스냅샷에서 사라지면
        # 다음 회차에 '처음 보는 건'이 되어 또 누락된다.
        rows = {"old": task("working")}
        repo = FakeTicketRepository(rows)
        w = CompletionWatcher(repo, StateStore(str(tmp_path / "s.json")))
        w.poll()

        w.track("t-invisible")                    # 목록 API에는 아직 안 보임
        w.poll()
        assert "t-invisible" in w.state.load()


class TestServiceCallback:
    def test_티켓_생성시_콜백이_호출된다(self):
        seen = []
        tickets = FakeTicketRepository()
        handle_request("E230096 층내 이전", tickets, FakeCustomerRepository(),
                       dt.date(2026, 9, 2), on_created=seen.append)
        assert seen == ["fake-1"]

    def test_대상이_아니면_콜백도_없다(self):
        seen = []
        tickets = FakeTicketRepository()
        handle_request("점심 뭐 먹지", tickets, FakeCustomerRepository(),
                       dt.date(2026, 9, 2), on_created=seen.append)
        assert seen == []

    def test_콜백이_터져도_접수는_성공한다(self):
        def boom(_):
            raise RuntimeError("스냅샷 저장 실패")

        tickets = FakeTicketRepository()
        got = handle_request("E230096 층내 이전", tickets, FakeCustomerRepository(),
                             dt.date(2026, 9, 2), on_created=boom)
        assert got and "접수되었습니다" in got

"""완료 감지 폴링."""
import json
import os

import pytest

from support.repository import FakeTicketRepository
from support.ticket import ORIGIN_LINE
from support.watcher import CompletionWatcher, StateStore, newly_closed

ORIGIN_CH = "4412501746823008358"
ORIGIN_MSG = "4412450644624024833"
BODY = "[원문]\n요청\n\n" + ORIGIN_LINE.format(channel=ORIGIN_CH, message=ORIGIN_MSG)


def task(state: str, body: str = BODY, subject: str = "비엔케이자산운용 이전 [접수 9/15]") -> dict:
    return {"subject": subject, "workflowClass": state,
            "body": {"mimeType": "text/x-markdown", "content": body}}


class TestNewlyClosed:
    def test_미완료에서_완료로_바뀐_건(self):
        assert newly_closed({"a": "working"}, {"a": "closed"}) == ["a"]

    def test_계속_완료인_건은_제외(self):
        assert newly_closed({"a": "closed"}, {"a": "closed"}) == []

    def test_처음_보는데_이미_완료면_제외(self):
        # 우리가 접수한 뒤 완료된 게 아니라 뒤늦게 시야에 들어온 건일 수 있다
        assert newly_closed({}, {"a": "closed"}) == []

    def test_미완료로_남은_건은_제외(self):
        assert newly_closed({"a": "registered"}, {"a": "working"}) == []

    def test_되돌린_뒤_다시_완료하면_다시_잡힌다(self):
        assert newly_closed({"a": "registered"}, {"a": "closed"}) == ["a"]

    def test_복수_건(self):
        prev = {"a": "working", "b": "closed", "c": "registered"}
        cur = {"a": "closed", "b": "closed", "c": "closed"}
        assert sorted(newly_closed(prev, cur)) == ["a", "c"]


class TestStateStore:
    def test_없으면_None(self, tmp_path):
        assert StateStore(str(tmp_path / "s.json")).load() is None

    def test_저장하고_읽는다(self, tmp_path):
        s = StateStore(str(tmp_path / "s.json"))
        s.save({"a": "closed"})
        assert s.load() == {"a": "closed"}

    def test_깨진_파일은_첫_실행으로_처리(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text("{깨진 json", encoding="utf-8")
        assert StateStore(str(p)).load() is None

    def test_중간_디렉터리를_만든다(self, tmp_path):
        s = StateStore(str(tmp_path / "sub" / "dir" / "s.json"))
        s.save({"a": "closed"})
        assert s.load() == {"a": "closed"}


class TestWatcher:
    def test_첫_폴링은_통보하지_않고_스냅샷만_저장(self, tmp_path):
        # 그러지 않으면 기존 완료 건 전부에 뒤늦은 알림이 나간다
        repo = FakeTicketRepository({"t1": task("closed")})
        w = CompletionWatcher(repo, StateStore(str(tmp_path / "s.json")))
        got = w.poll()
        assert got.seeded and got.replies == []

    def test_두_번째_폴링에서_완료를_감지(self, tmp_path):
        rows = {"t1": task("working")}
        repo = FakeTicketRepository(rows)
        w = CompletionWatcher(repo, StateStore(str(tmp_path / "s.json")))
        w.poll()                                  # 시딩

        rows["t1"] = task("closed")
        got = w.poll()
        assert len(got.replies) == 1
        assert got.replies[0].channel == ORIGIN_CH
        assert got.replies[0].message_id == ORIGIN_MSG
        assert "처리 완료" in got.replies[0].text

    def test_같은_완료를_두_번_통보하지_않는다(self, tmp_path):
        rows = {"t1": task("working")}
        repo = FakeTicketRepository(rows)
        w = CompletionWatcher(repo, StateStore(str(tmp_path / "s.json")))
        w.poll()
        rows["t1"] = task("closed")
        assert len(w.poll().replies) == 1
        assert w.poll().replies == []             # 두 번째 폴링에선 조용

    def test_우리가_만든_티켓이_아니면_통보하지_않는다(self, tmp_path):
        rows = {"t1": task("working", body="사람이 직접 만든 업무")}
        repo = FakeTicketRepository(rows)
        w = CompletionWatcher(repo, StateStore(str(tmp_path / "s.json")))
        w.poll()
        rows["t1"] = task("closed", body="사람이 직접 만든 업무")
        assert w.poll().replies == []

    def test_재시작해도_상태가_이어진다(self, tmp_path):
        path = str(tmp_path / "s.json")
        rows = {"t1": task("working")}
        repo = FakeTicketRepository(rows)
        CompletionWatcher(repo, StateStore(path)).poll()     # 시딩 후 종료

        rows["t1"] = task("closed")
        # 새 인스턴스 = 프로세스 재시작
        got = CompletionWatcher(repo, StateStore(path)).poll()
        assert len(got.replies) == 1

    def test_목록_조회_실패시_조용히_넘어간다(self, tmp_path):
        class Broken:
            def list_states(self):
                raise RuntimeError("Dooray 500")

        w = CompletionWatcher(Broken(), StateStore(str(tmp_path / "s.json")))
        got = w.poll()
        assert got.replies == [] and not got.seeded

    def test_상세_조회_실패해도_나머지는_처리한다(self, tmp_path):
        rows = {"t1": task("working"), "t2": task("working")}

        class Partial(FakeTicketRepository):
            def get(self, post_id):
                if post_id == "t1":
                    raise RuntimeError("일시 오류")
                return super().get(post_id)

        repo = Partial(rows)
        w = CompletionWatcher(repo, StateStore(str(tmp_path / "s.json")))
        w.poll()
        rows["t1"] = task("closed")
        rows["t2"] = task("closed")
        assert len(w.poll().replies) == 1        # t2만 통보

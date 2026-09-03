"""슬래시 커맨드 버튼 — 목록 생성과 클릭 파싱."""
from support.command import (
    ACTION_ACCEPT,
    ACTION_DONE,
    CALLBACK_TICKET,
    build_error,
    build_result,
    build_ticket_list,
    parse_action,
)

TASKS = [
    {"id": "t1", "number": 1, "subject": "비엔케이자산운용 노후교체 [접수 9/10]",
     "workflowClass": "registered"},
    {"id": "t2", "number": 2, "subject": "한국거래소 SW 업그레이드 [접수]",
     "workflowClass": "working"},
    {"id": "t3", "number": 3, "subject": "끝난 건", "workflowClass": "closed"},
]


class TestTicketList:
    def test_완료된_건은_빼고_보여준다(self):
        got = build_ticket_list(TASKS)
        titles = [a["title"] for a in got["attachments"]]
        assert len(titles) == 2 and "끝난 건" not in titles

    def test_본인에게만_보인다(self):
        # 대화방 전체에 남의 요청 목록이 뿌려지면 안 된다
        assert build_ticket_list(TASKS)["responseType"] == "ephemeral"

    def test_접수_상태는_수락과_완료_둘_다(self):
        got = build_ticket_list(TASKS)
        acts = got["attachments"][0]["actions"]
        assert [a["text"] for a in acts] == ["수락", "완료"]

    def test_진행중은_완료만(self):
        # 이미 수락한 건에 또 수락 버튼을 보여주지 않는다
        got = build_ticket_list(TASKS)
        acts = got["attachments"][1]["actions"]
        assert [a["text"] for a in acts] == ["완료"]

    def test_버튼_값에_업무ID가_담긴다(self):
        got = build_ticket_list(TASKS)
        assert got["attachments"][0]["actions"][0]["value"] == f"{ACTION_ACCEPT}/t1"

    def test_callbackId로_우리_버튼임을_표시(self):
        got = build_ticket_list(TASKS)
        assert all(a["callbackId"] == CALLBACK_TICKET for a in got["attachments"])

    def test_처리할_게_없으면_안내만(self):
        got = build_ticket_list([{"id": "x", "workflowClass": "closed"}])
        assert "없습니다" in got["text"] and "attachments" not in got


class TestParseAction:
    def _payload(self, **kw):
        base = {"callbackId": CALLBACK_TICKET, "actionValue": f"{ACTION_DONE}/t1",
                "user": {"id": "u1"}, "channel": {"id": "c1"}}
        base.update(kw)
        return base

    def test_정상_파싱(self):
        got = parse_action(self._payload())
        assert got.action == ACTION_DONE and got.task_id == "t1"
        assert got.user_id == "u1" and got.channel_id == "c1"

    def test_다른_callbackId는_무시(self):
        # 같은 앱의 다른 커맨드 버튼이 섞여 들어올 수 있다
        assert parse_action(self._payload(callbackId="vote")) is None

    def test_모르는_동작은_무시(self):
        assert parse_action(self._payload(actionValue="delete/t1")) is None

    def test_형식이_틀리면_무시(self):
        for v in ("done", "", "/t1", "done/"):
            assert parse_action(self._payload(actionValue=v)) is None

    def test_빈_입력(self):
        assert parse_action({}) is None
        assert parse_action(None) is None


class TestResult:
    def _req(self, action=ACTION_DONE, task_id="t1"):
        from support.command import ActionRequest
        return ActionRequest(action=action, task_id=task_id)

    def test_원래_메시지를_갱신한다(self):
        got = build_result(self._req(), "비엔케이자산운용 노후교체", "closed", "정시욱")
        assert got["replaceOriginal"] is True
        assert "완료" in got["text"] and "정시욱" in got["text"]

    def test_오류도_같은_자리에서_알린다(self):
        got = build_error("업무를 찾을 수 없습니다.")
        assert got["replaceOriginal"] is True and "찾을 수 없" in got["text"]


class TestResultRefresh:
    """버튼을 눌러도 목록이 남아 있어야 연속으로 처리할 수 있다."""

    def _req(self, action, task_id):
        from support.command import ActionRequest
        return ActionRequest(action=action, task_id=task_id)

    def _after_accept(self):
        # t1을 수락한 뒤의 목록
        after = [dict(t) for t in TASKS]
        after[0]["workflowClass"] = "working"
        return build_result(self._req(ACTION_ACCEPT, "t1"),
                            after[0]["subject"], "working", tasks=after)

    def test_처리해도_목록이_남는다(self):
        got = self._after_accept()
        assert len(got["attachments"]) == 2      # 사라지지 않는다

    def test_처리한_건의_상태가_바뀌어_보인다(self):
        got = self._after_accept()
        assert "진행 중" in got["attachments"][0]["text"]

    def test_처리한_건에_수락_버튼이_사라진다(self):
        got = self._after_accept()
        acts = got["attachments"][0]["actions"]
        assert [a["text"] for a in acts] == ["완료"]

    def test_무엇을_처리했는지_위에_알린다(self):
        got = self._after_accept()
        assert "진행 중" in got["text"] and TASKS[0]["subject"] in got["text"]

    def test_완료하면_목록에서_빠진다(self):
        after = [dict(t) for t in TASKS]
        after[0]["workflowClass"] = "closed"
        got = build_result(self._req(ACTION_DONE, "t1"),
                           after[0]["subject"], "closed", tasks=after)
        titles = [a["title"] for a in got["attachments"]]
        assert TASKS[0]["subject"] not in titles and len(titles) == 1

    def test_마지막_건을_완료하면_안내만_남는다(self):
        got = build_result(self._req(ACTION_DONE, "t1"), "끝난 건", "closed",
                           tasks=[{"id": "t1", "workflowClass": "closed"}])
        assert "없습니다" in got["text"] and "attachments" not in got

    def test_목록_재조회에_실패해도_결과는_알린다(self):
        # 상태 변경은 이미 성공했다. 화면 갱신 실패로 삼켜서는 안 된다.
        got = build_result(self._req(ACTION_DONE, "t1"), "한국거래소 SW 업그레이드",
                           "closed", tasks=None)
        assert got["replaceOriginal"] is True
        assert "완료" in got["text"] and "attachments" not in got

    def test_그_자리에서_갈아끼운다(self):
        got = self._after_accept()
        assert got["replaceOriginal"] is True and got["responseType"] == "ephemeral"

    def test_오류도_같은_자리에서_알린다(self):
        got = build_error("업무를 찾을 수 없습니다.")
        assert got["replaceOriginal"] is True and "찾을 수 없" in got["text"]

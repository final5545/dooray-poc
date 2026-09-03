"""슬래시 커맨드 버튼 — 목록 생성과 클릭 파싱."""
from support.command import (
    ACTION_ACCEPT,
    ACTION_DONE,
    ACTION_UNDO,
    ACTION_CREATE,
    CALLBACK_FORM,
    CALLBACK_TICKET,
    build_announcement,
    build_form_confirm,
    build_form_result,
    build_error,
    build_result,
    build_ticket_list,
    parse_action,
    parse_form_action,
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

    def test_버튼_값에_업무ID와_누를_당시_상태가_담긴다(self):
        # 세 번째 칸이 되돌리기 목적지다
        got = build_ticket_list(TASKS)
        assert got["attachments"][0]["actions"][0]["value"] == \
            f"{ACTION_ACCEPT}/t1/registered"

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

    def _req(self, action, task_id, prev_state="registered"):
        from support.command import ActionRequest
        return ActionRequest(action=action, task_id=task_id, prev_state=prev_state)

    def _after_accept(self):
        # t1을 수락한 뒤의 목록
        after = [dict(t) for t in TASKS]
        after[0]["workflowClass"] = "working"
        return build_result(self._req(ACTION_ACCEPT, "t1"),
                            after[0]["subject"], "working", tasks=after)

    def test_처리해도_목록이_남는다(self):
        got = self._after_accept()
        assert len(got["attachments"]) == 3      # 처리 결과 1 + 남은 2건

    def test_처리한_건의_상태가_바뀌어_보인다(self):
        got = self._after_accept()
        assert "진행 중" in got["attachments"][1]["text"]

    def test_처리한_건에_수락_버튼이_사라진다(self):
        got = self._after_accept()
        acts = got["attachments"][1]["actions"]
        assert [a["text"] for a in acts] == ["완료"]

    def test_무엇을_처리했는지_맨_위에_알린다(self):
        got = self._after_accept()
        assert "진행 중" in got["attachments"][0]["text"]
        assert TASKS[0]["subject"] in got["attachments"][0]["text"]

    def test_완료하면_목록에서_빠진다(self):
        after = [dict(t) for t in TASKS]
        after[0]["workflowClass"] = "closed"
        got = build_result(self._req(ACTION_DONE, "t1"),
                           after[0]["subject"], "closed", tasks=after)
        titles = [a.get("title") for a in got["attachments"]]
        assert TASKS[0]["subject"] not in titles
        assert len([t for t in titles if t]) == 1

    def test_마지막_건을_완료하면_안내만_남는다(self):
        got = build_result(self._req(ACTION_DONE, "t1"), "끝난 건", "closed",
                           tasks=[{"id": "t1", "workflowClass": "closed"}])
        # 목록은 비지만 되돌리기 손잡이는 남아야 한다
        assert "없습니다" in got["text"]
        assert len(got["attachments"]) == 1 and got["attachments"][0]["actions"]

    def test_목록_재조회에_실패해도_결과는_알린다(self):
        # 상태 변경은 이미 성공했다. 화면 갱신 실패로 삼켜서는 안 된다.
        got = build_result(self._req(ACTION_DONE, "t1"), "한국거래소 SW 업그레이드",
                           "closed", tasks=None)
        assert got["replaceOriginal"] is True and "완료" in got["text"]

    def test_그_자리에서_갈아끼운다(self):
        got = self._after_accept()
        assert got["replaceOriginal"] is True and got["responseType"] == "ephemeral"

    def test_오류도_같은_자리에서_알린다(self):
        got = build_error("업무를 찾을 수 없습니다.")
        assert got["replaceOriginal"] is True and "찾을 수 없" in got["text"]


class TestUndo:
    """완료 버튼을 잘못 눌렀을 때 되돌릴 수 있어야 한다.

    완료하면 목록에서 사라지므로, 붙잡을 손잡이는 처리 결과 카드뿐이다.
    되돌릴 목적지는 **누를 당시 상태**다 — 완료 버튼은 접수에서도 진행 중에서도
    보이므로, 클릭 후에 조회해 봐야 이미 바뀐 뒤라 알 수 없다.
    """

    def _req(self, action, task_id="t1", prev_state="registered"):
        from support.command import ActionRequest
        return ActionRequest(action=action, task_id=task_id, prev_state=prev_state)

    def _done_from(self, prev_state):
        after = [{"id": "t1", "subject": "끝낸 건", "workflowClass": "closed"}]
        return build_result(self._req(ACTION_DONE, prev_state=prev_state),
                            "끝낸 건", "closed", tasks=after)

    # --- 버튼이 달리는가 ---

    def test_처리_결과에_되돌리기가_달린다(self):
        acts = self._done_from("registered")["attachments"][0]["actions"]
        assert len(acts) == 1 and acts[0]["text"].startswith("되돌리기")

    def test_접수에서_완료했으면_접수로_되돌린다(self):
        a = self._done_from("registered")["attachments"][0]["actions"][0]
        assert a["value"] == f"{ACTION_UNDO}/t1/registered"
        assert "접수" in a["text"]

    def test_진행중에서_완료했으면_진행중으로_되돌린다(self):
        # 같은 완료 버튼이라도 어디서 눌렀느냐에 따라 목적지가 다르다
        a = self._done_from("working")["attachments"][0]["actions"][0]
        assert a["value"] == f"{ACTION_UNDO}/t1/working"
        assert "진행 중" in a["text"]

    def test_수락도_되돌릴_수_있다(self):
        got = build_result(self._req(ACTION_ACCEPT, prev_state="registered"),
                           "수락한 건", "working",
                           tasks=[{"id": "t1", "subject": "수락한 건",
                                   "workflowClass": "working"}])
        assert got["attachments"][0]["actions"][0]["value"] == \
            f"{ACTION_UNDO}/t1/registered"

    def test_되돌린_뒤에는_또_되돌리기를_달지_않는다(self):
        # 목록에 다시 나타났으므로 거기서 누르면 된다
        got = build_result(self._req(ACTION_UNDO, prev_state="registered"),
                           "되살린 건", "registered",
                           tasks=[{"id": "t1", "subject": "되살린 건",
                                   "workflowClass": "registered"}])
        assert "actions" not in got["attachments"][0]

    def test_되돌렸다고_말한다(self):
        got = build_result(self._req(ACTION_UNDO, prev_state="working"),
                           "되살린 건", "working", tasks=[])
        assert "되돌렸습니다" in got["attachments"][0]["text"]

    def test_누를_당시_상태를_모르면_되돌리기가_없다(self):
        # requester 줄이 없던 시절처럼, 옛 형식 버튼에서 온 클릭
        got = build_result(self._req(ACTION_DONE, prev_state=None),
                           "끝낸 건", "closed", tasks=[])
        assert "actions" not in got["attachments"][0]

    # --- 파싱과 목적지 ---

    def _payload(self, value):
        return {"callbackId": CALLBACK_TICKET, "actionValue": value,
                "user": {"id": "u1"}, "channel": {"id": "c1"}}

    def test_되돌리기_클릭을_파싱한다(self):
        got = parse_action(self._payload(f"{ACTION_UNDO}/t1/working"))
        assert got.action == ACTION_UNDO and got.prev_state == "working"

    def test_되돌리기는_목적지가_없으면_무시(self):
        assert parse_action(self._payload(f"{ACTION_UNDO}/t1")) is None

    def test_모르는_상태는_무시(self):
        # 남이 값을 바꿔 보내도 아무 상태로나 못 바꾼다
        assert parse_action(self._payload(f"{ACTION_DONE}/t1/deleted")) is None

    def test_칸이_너무_많으면_무시(self):
        assert parse_action(self._payload(f"{ACTION_DONE}/t1/working/extra")) is None

    def test_목적지는_동작이_결정한다(self):
        assert parse_action(self._payload(f"{ACTION_DONE}/t1/working")).target_state \
            == "closed"
        assert parse_action(self._payload(f"{ACTION_ACCEPT}/t1/registered")).target_state \
            == "working"
        assert parse_action(self._payload(f"{ACTION_UNDO}/t1/registered")).target_state \
            == "registered"


class TestAnnouncement:
    """완료를 방에 봇 이름으로 공지한다.

    ephemeral 결과는 누른 사람만 본다. 요청자에게 결과가 닿으려면 방에 남아야
    하는데, responseUrl로 보내면 앱 이름(기술지원 도우미 BOT)으로 나간다.
    개인 계정 발신과 달리 자동화가 한 일임이 드러난다.

    ⚠️ responseUrl의 cmdToken은 **호출 1건에 딸려 오는 값**이다. 앱 토큰으로는
       만들 수 없다(실측: INTEGRATION_COMMAND_CALL_NOT_EXIST_ERROR).
    """

    def test_방_전체에_보인다(self):
        got = build_announcement("한국거래소 SW 업그레이드")
        assert got["responseType"] == "inChannel"

    def test_기존_메시지를_덮지_않는다(self):
        # 목록 갱신과 달리 새 메시지로 남아야 요청자가 본다
        assert build_announcement("건")["replaceOriginal"] is False

    def test_업무_제목이_카드에_붙는다(self):
        got = build_announcement("한국거래소 SW 업그레이드")
        assert got["attachments"][0]["title"] == "한국거래소 SW 업그레이드"

    def test_제목이_없으면_카드에_제목도_없다(self):
        assert "title" not in build_announcement("")["attachments"][0]

    def test_처리자를_밝힐_수_있다(self):
        assert "정시욱" in build_announcement("건", "정시욱")["text"]


class TestResponseUrl:
    def test_클릭_페이로드에서_responseUrl을_챙긴다(self):
        got = parse_action({
            "callbackId": CALLBACK_TICKET, "actionValue": f"{ACTION_DONE}/t1/working",
            "channelId": "c9", "responseUrl": "https://x/hook/tok",
        })
        assert got.response_url == "https://x/hook/tok" and got.channel_id == "c9"

    def test_responseUrl이_없어도_처리는_된다(self):
        # 봇 공지는 부가 기능이다. 없다고 상태 변경까지 막으면 안 된다
        got = parse_action({"callbackId": CALLBACK_TICKET,
                            "actionValue": f"{ACTION_DONE}/t1/working"})
        assert got is not None and got.response_url is None


class TestFormConfirmButtons:
    """접수 확인은 커맨드 응답이라 버튼이 실제로 동작한다.

    일반 메시지의 버튼은 클릭이 전달되지 않는다(2026-09-03 실측). 그래서
    양식 제출은 일반 메시지로 받고, 확인만 커맨드 응답으로 띄운다.
    """
    KEY = "ch-1.user-1"

    def test_생성과_취소_버튼이_나온다(self):
        got = build_form_confirm("아래 내용으로 업무를 생성할까요?\n\n제목 : 건", self.KEY)
        acts = got["attachments"][0]["actions"]
        assert [a["text"] for a in acts] == ["생성", "취소"]

    def test_버튼에_대기_식별자가_담긴다(self):
        got = build_form_confirm("머리\n본문", self.KEY)
        assert got["attachments"][0]["actions"][0]["value"] == f"{ACTION_CREATE}/{self.KEY}"

    def test_본인에게만_보인다(self):
        assert build_form_confirm("머리\n본문", self.KEY)["responseType"] == "ephemeral"

    def test_첫_줄이_제목이_되고_나머지가_본문(self):
        got = build_form_confirm("아래 내용으로 업무를 생성할까요?\n\n제목 : 건", self.KEY)
        assert got["text"] == "아래 내용으로 업무를 생성할까요?"
        assert "제목 : 건" in got["attachments"][0]["text"]

    def test_클릭을_파싱한다(self):
        got = parse_form_action({"callbackId": CALLBACK_FORM,
                                 "actionValue": f"{ACTION_CREATE}/{self.KEY}"})
        assert got.action == ACTION_CREATE and got.key == self.KEY

    def test_티켓_버튼과_섞이지_않는다(self):
        assert parse_form_action({"callbackId": CALLBACK_TICKET,
                                  "actionValue": "done/t1/working"}) is None
        assert parse_action({"callbackId": CALLBACK_FORM,
                             "actionValue": f"{ACTION_CREATE}/{self.KEY}"}) is None

    def test_형식이_틀리면_무시(self):
        for v in ("create", "", "create/", "/key", "create/a/b"):
            assert parse_form_action({"callbackId": CALLBACK_FORM,
                                      "actionValue": v}) is None

    def test_결과는_그_자리를_갈아끼운다(self):
        got = build_form_result("요청을 취소했습니다.")
        assert got["replaceOriginal"] is True and "취소" in got["text"]

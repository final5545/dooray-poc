"""완료 알림 → 원 요청 회신 지시."""
import pytest

from support.completion import handle_news
from support.repository import FakeTicketRepository
from support.ticket import ORIGIN_LINE
from tests.test_notify import REAL_FRAME

TASK_ID = "4412603105543031023"
ORIGIN_CH = "4412501746823008358"
ORIGIN_MSG = "4412450644624024833"

BODY_WITH_ORIGIN = (
    "[고객사] 비엔케이자산운용\n"
    "[고객 고유 번호(추출)] E21016\n\n"
    "[원문]\nE21016 층내 이전 요청\n\n"
    + ORIGIN_LINE.format(channel=ORIGIN_CH, message=ORIGIN_MSG)
    + "\n— AI 자동 등록 (기술지원 요청 자동화 PoC)"
)


def repo(**task) -> FakeTicketRepository:
    base = {
        "subject": "비엔케이자산운용 장비/설비 이전 [접수 9/15]",
        "workflowClass": "closed",
        "body": {"mimeType": "text/x-markdown", "content": BODY_WITH_ORIGIN},
    }
    base.update(task)
    return FakeTicketRepository({TASK_ID: base})


class TestHandleNews:
    def test_완료_알림이면_회신_지시를_돌려준다(self):
        got = handle_news(REAL_FRAME, repo())
        assert got is not None
        assert got.channel == ORIGIN_CH
        assert got.message_id == ORIGIN_MSG
        assert "처리 완료" in got.text

    def test_회신문에_제목과_처리자가_들어간다(self):
        got = handle_news(REAL_FRAME, repo())
        assert "비엔케이자산운용" in got.text
        assert "정시욱" in got.text

    def test_완료가_아니면_통보하지_않는다(self):
        # 담당자 변경·태그 추가 등도 같은 채널로 알림이 온다
        for cls in ("registered", "working", None):
            assert handle_news(REAL_FRAME, repo(workflowClass=cls)) is None

    def test_원_요청_좌표가_없으면_통보하지_않는다(self):
        # 우리 봇이 만든 티켓이 아니면 회신할 곳이 없다
        body = {"mimeType": "text/x-markdown", "content": "사람이 직접 만든 업무"}
        assert handle_news(REAL_FRAME, repo(body=body)) is None

    def test_업무를_못_찾으면_None(self):
        assert handle_news(REAL_FRAME, FakeTicketRepository({})) is None

    def test_업무_알림이_아니면_None(self):
        frame = {"content": dict(REAL_FRAME["content"], attachments=[])}
        assert handle_news(frame, repo()) is None

    def test_다른_프로젝트_알림은_조회조차_하지_않는다(self):
        # News에는 참여 중인 전 프로젝트 알림이 들어온다.
        # 필터가 없으면 권한 없는 프로젝트에 조회를 날려 403을 맞는다.
        class Spy:
            called = False

            def get(self, post_id):
                Spy.called = True
                return {}

        spy = Spy()
        assert handle_news(REAL_FRAME, spy, project_code="다른-프로젝트") is None
        assert not Spy.called, "다른 프로젝트인데 조회를 시도했다"

    def test_같은_프로젝트면_정상_처리(self):
        got = handle_news(REAL_FRAME, repo(), project_code="AI-PoC-Agent-Test")
        assert got is not None and got.channel == ORIGIN_CH

    def test_프로젝트_코드를_안_주면_필터하지_않는다(self):
        assert handle_news(REAL_FRAME, repo()) is not None

    def test_조회_실패해도_예외를_던지지_않는다(self):
        class Broken:
            def get(self, post_id):
                raise RuntimeError("Dooray 500")

        assert handle_news(REAL_FRAME, Broken()) is None


class TestOriginRoundTrip:
    def test_티켓_생성_본문에서_좌표를_되읽을_수_있다(self):
        import datetime as dt

        from crm.client import FakeCustomerRepository
        from support.service import handle_request
        from support.ticket import parse_origin

        tickets = FakeTicketRepository()
        handle_request("E230096 층내 이전 요청", tickets, FakeCustomerRepository(),
                       dt.date(2026, 9, 2),
                       origin_channel=ORIGIN_CH, origin_message=ORIGIN_MSG)
        _, body = tickets.created[0]
        assert parse_origin(body) == (ORIGIN_CH, ORIGIN_MSG)

    def test_좌표를_안_넘기면_본문에도_없다(self):
        import datetime as dt

        from crm.client import FakeCustomerRepository
        from support.service import handle_request
        from support.ticket import parse_origin

        tickets = FakeTicketRepository()
        handle_request("E230096 층내 이전", tickets, FakeCustomerRepository(),
                       dt.date(2026, 9, 2))
        _, body = tickets.created[0]
        assert parse_origin(body) is None

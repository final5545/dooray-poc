"""요청자 참조자 지정 — 완료 알림을 Dooray 기본 기능에 위임하는 경로."""
import datetime as dt

import pytest

from crm.client import FakeCustomerRepository
from support.repository import FakeTicketRepository
from support.service import handle_request

TODAY = dt.date(2026, 9, 2)
REQUESTER = "3267267451433100066"
TEXT = "E230096 층내 이전 요청드립니다"


@pytest.fixture
def tickets():
    return FakeTicketRepository()


@pytest.fixture
def customers():
    return FakeCustomerRepository()


class TestRequesterCc:
    def test_요청자가_참조자로_들어간다(self, tickets, customers):
        handle_request(TEXT, tickets, customers, TODAY, requester_id=REQUESTER)
        assert tickets.cc[0] == [REQUESTER]

    def test_요청자를_모르면_참조자를_비운다(self, tickets, customers):
        handle_request(TEXT, tickets, customers, TODAY)
        assert tickets.cc[0] == []

    def test_대상이_아니면_티켓도_참조자도_없다(self, tickets, customers):
        assert handle_request("점심 뭐 먹지", tickets, customers, TODAY,
                              requester_id=REQUESTER) is None
        assert tickets.created == []
        assert tickets.cc == []


class TestPayload:
    def test_REST_페이로드에_cc가_들어간다(self):
        captured = {}

        class Spy:
            def create(self, subject, body, cc=None):
                captured["cc"] = cc
                return "post-1"

        handle_request(TEXT, Spy(), None, TODAY, requester_id=REQUESTER)
        assert captured["cc"] == [REQUESTER]

    def test_cc_인자를_받지_않는_저장소는_깨진다(self):
        # 인터페이스가 바뀌었으므로 구현체도 따라와야 한다는 것을 명시적으로 고정
        class Old:
            def create(self, subject, body):
                return "post-1"

        got = handle_request(TEXT, Old(), None, TODAY, requester_id=REQUESTER)
        assert got and "오류가 발생" in got

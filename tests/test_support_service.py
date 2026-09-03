import datetime as dt

import pytest

from crm.client import FakeCustomerRepository
from support.repository import FakeTicketRepository
from support.service import handle_request

TODAY = dt.date(2026, 8, 1)


@pytest.fixture
def tickets():
    return FakeTicketRepository()


@pytest.fixture
def customers():
    return FakeCustomerRepository()


class TestHandleRequest:
    def test_티켓이_생성된다(self, tickets, customers):
        got = handle_request("E230096 신규설치 부탁드립니다", tickets, customers, TODAY)
        assert got and "접수되었습니다" in got
        assert len(tickets.created) == 1

    def test_고객사명을_CRM에서_가져온다(self, tickets, customers):
        handle_request("E230096 신규설치", tickets, customers, TODAY)
        subject, _ = tickets.created[0]
        assert "미래에셋자산운용" in subject

    def test_고객번호가_없으면_None이고_티켓도_안_만든다(self, tickets, customers):
        for text in ["점심 뭐 먹지", "", "회의 3시"]:
            assert handle_request(text, tickets, customers, TODAY) is None
        assert tickets.created == []

    def test_CRM_없이도_동작한다(self, tickets):
        got = handle_request("E230096 신규설치", tickets, None, TODAY)
        assert got and len(tickets.created) == 1

    def test_CRM_조회_실패해도_티켓은_만든다(self, tickets):
        class Broken:
            def fetch(self, code):
                raise RuntimeError("CRM 다운")

        got = handle_request("E230096 신규설치", tickets, Broken(), TODAY)
        assert got and len(tickets.created) == 1

    def test_미등록_고객번호도_티켓은_만든다(self, tickets, customers):
        # CRM에 없어도 기술지원 요청 자체는 접수되어야 한다
        got = handle_request("E999999 장애 발생", tickets, customers, TODAY)
        assert got and len(tickets.created) == 1

    def test_티켓_생성_실패시_내부오류를_노출하지_않는다(self, customers):
        class Broken:
            def create(self, subject, body):
                raise RuntimeError("Dooray 500")

        got = handle_request("E230096 신규설치", Broken(), customers, TODAY)
        assert got and "오류가 발생" in got
        assert "Dooray 500" not in got and "RuntimeError" not in got

"""하이브리드 추출 — 정규식과 LLM의 역할 분담이 지켜지는지 검증."""
import datetime as dt

import pytest

from crm.client import FakeCustomerRepository
from support.llm import Enrichment
from support.repository import FakeTicketRepository
from support.service import handle_request

TODAY = dt.date(2026, 9, 2)

# 로그에서 실제로 관측된 요청문 (고객사명이 본문에만 있고 CRM에는 없는 케이스)
REAL_CASE = """비엔케이자산운용
E21016, E200105 층내 이전 요청으로 부탁드립니다.
희망일정 : 8월 28일(금) 오후 4시 이후
담당자 : 김수빈 파트너 010-6265-4782"""


class FakeLLM:
    def __init__(self, enrichment: Enrichment | None = None, boom: bool = False):
        self._e = enrichment or Enrichment()
        self._boom = boom
        self.calls = 0

    def enrich(self, text, base):
        self.calls += 1
        if self._boom:
            raise RuntimeError("LLM 다운")
        return self._e


@pytest.fixture
def tickets():
    return FakeTicketRepository()


class TestCustomerName:
    def test_CRM에_없으면_LLM_추출값을_쓴다(self, tickets):
        llm = FakeLLM(Enrichment(customer_name="비엔케이자산운용"))
        handle_request(REAL_CASE, tickets, FakeCustomerRepository(), TODAY, llm)
        subject, _ = tickets.created[0]
        assert "비엔케이자산운용" in subject

    def test_CRM_조회가_되면_CRM이_우선한다(self, tickets):
        # LLM이 다른 이름을 줘도 CRM 값이 이긴다
        llm = FakeLLM(Enrichment(customer_name="엉뚱한회사"))
        handle_request("E230096 신규설치", tickets, FakeCustomerRepository(), TODAY, llm)
        subject, _ = tickets.created[0]
        assert "미래에셋자산운용" in subject
        assert "엉뚱한회사" not in subject


class TestRegexWins:
    def test_정규식이_잡은_유형을_LLM이_덮어쓰지_못한다(self, tickets):
        llm = FakeLLM(Enrichment(request_type="신규설치"))
        handle_request(REAL_CASE, tickets, FakeCustomerRepository(), TODAY, llm)
        subject, _ = tickets.created[0]
        assert "장비/설비 이전" in subject
        assert "신규설치" not in subject

    def test_정규식이_못_잡은_유형만_LLM이_채운다(self, tickets):
        llm = FakeLLM(Enrichment(request_type="장애"))
        # '조회가 안 되네요' 는 키워드 목록에 없다
        handle_request("E230096 조회가 안 되네요", tickets, FakeCustomerRepository(), TODAY, llm)
        subject, _ = tickets.created[0]
        assert "장애" in subject

    def test_고객번호는_LLM이_건드리지_않는다(self, tickets):
        llm = FakeLLM(Enrichment(customer_name="비엔케이자산운용"))
        got = handle_request(REAL_CASE, tickets, FakeCustomerRepository(), TODAY, llm)
        assert "E21016, E200105" in got


class TestBodyEnrichment:
    def test_세부사항과_담당자가_본문에_들어간다(self, tickets):
        llm = FakeLLM(Enrichment(detail="층내 이전", contact="김수빈 파트너 010-6265-4782"))
        handle_request(REAL_CASE, tickets, FakeCustomerRepository(), TODAY, llm)
        _, body = tickets.created[0]
        assert "[세부 사항] 층내 이전" in body
        assert "[담당자] 김수빈 파트너" in body

    def test_보강값이_없으면_행을_생략한다(self, tickets):
        handle_request(REAL_CASE, tickets, FakeCustomerRepository(), TODAY, FakeLLM())
        _, body = tickets.created[0]
        assert "[세부 사항]" not in body
        assert "[담당자]" not in body


class TestResilience:
    def test_LLM이_죽어도_티켓은_생성된다(self, tickets):
        llm = FakeLLM(boom=True)
        got = handle_request(REAL_CASE, tickets, FakeCustomerRepository(), TODAY, llm)
        assert got and len(tickets.created) == 1
        assert "장비/설비 이전" in tickets.created[0][0]

    def test_LLM_없이도_동작한다(self, tickets):
        got = handle_request(REAL_CASE, tickets, FakeCustomerRepository(), TODAY, None)
        assert got and len(tickets.created) == 1

    def test_대상이_아니면_LLM을_부르지_않는다(self, tickets):
        # 고객번호 없는 잡담에 LLM 비용을 쓰지 않는다
        llm = FakeLLM()
        assert handle_request("점심 뭐 먹지", tickets, FakeCustomerRepository(), TODAY, llm) is None
        assert llm.calls == 0

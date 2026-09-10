"""요청서 접수 창구 — #명령으로 도는 대화 흐름.

확인을 버튼으로 하지 못하는 이유는 support/form.py 머리말 참조
(2026-09-03 실측: 일반 메시지의 버튼은 클릭이 전달되지 않는다).
"""
import datetime as dt

import pytest

from crm.client import FakeCustomerRepository
from support.intake import PendingStore, handle
from support.repository import FakeTicketRepository

TODAY = dt.date(2026, 9, 3)
CH, USER, OTHER = "ch-1", "user-1", "user-2"

FILLED = """이전요청서
[기본정보]
고객번호 : E230096
고객명 : 미래에셋자산운용 정상호 매니저
[요청정보]
희망일시 : 2026년 8월 30일 오후 4시 이후
연락처 : 02-3774-8013
메모 : 이전 간 모니터 2대 추가"""


@pytest.fixture
def tickets():
    return FakeTicketRepository()


@pytest.fixture
def store():
    return PendingStore()


def call(text, store, tickets=None, user=USER, channel=CH, **kw):
    return handle(text, channel=channel, user_id=user, store=store,
                  tickets=tickets, customers=FakeCustomerRepository(),
                  today=TODAY, **kw)


class TestPassthrough:
    def test_일반_메시지는_건드리지_않는다(self, store):
        # None이어야 호출자가 평소대로 고객번호 조회로 넘어간다
        assert call("E230096 계약 언제 끝나지?", store) is None

    def test_모르는_명령도_넘긴다(self, store):
        assert call("#점심", store) is None


class TestFormDelivery:
    def test_빈_양식을_준다(self, store):
        got = call("#이전", store)
        assert got.startswith("이전요청서") and "고객번호 : " in got

    def test_양식_목록을_준다(self, store):
        assert "#이전" in call("#양식", store)


class TestSubmit:
    def test_바로_만들지_않고_확인을_묻는다(self, store, tickets):
        got = call(f"#기술정보\n{FILLED}", store, tickets)
        assert "생성할까요" in got
        assert tickets.created == []          # 아직 만들면 안 된다

    def test_확인_화면에_읽은_값이_보인다(self, store, tickets):
        got = call(f"#기술정보\n{FILLED}", store, tickets)
        assert "E230096" in got and "모니터 2대" in got

    def test_제목은_CRM_고객사명으로_만든다(self, store, tickets):
        # 양식의 고객명에는 담당자까지 섞여 있어 제목으로 쓰기엔 길다
        got = call(f"#기술정보\n{FILLED}", store, tickets)
        assert "미래에셋자산운용 장비/설비 이전 [접수 8/30]" in got

    def test_양식이_비면_안내한다(self, store, tickets):
        assert "붙여" in call("#기술정보", store, tickets)

    def test_고객번호가_없으면_거절한다(self, store, tickets):
        got = call("#기술정보\n이전요청서\n메모 : 급합니다", store, tickets)
        assert "고객번호" in got and tickets.created == []


class TestConfirm:
    def _submit(self, store, tickets, **kw):
        call(f"#기술정보\n{FILLED}", store, tickets, **kw)

    def test_확인하면_업무가_만들어진다(self, store, tickets):
        self._submit(store, tickets)
        got = call("#확인", store, tickets)
        assert len(tickets.created) == 1
        assert "접수되었습니다" in got and "E230096" in got

    def test_본문에_원_요청_좌표와_요청자가_남는다(self, store, tickets):
        # 완료 통보가 이 대화방·메시지로 돌아와야 한다
        call(f"#기술정보\n{FILLED}", store, tickets, origin_message="msg-9")
        call("#확인", store, tickets)
        body = tickets.created[0][1]
        assert f"channel={CH}" in body and "message=msg-9" in body
        assert f"requester={USER}" in body

    def test_메모와_연락처가_본문에_들어간다(self, store, tickets):
        self._submit(store, tickets)
        call("#확인", store, tickets)
        body = tickets.created[0][1]
        assert "모니터 2대" in body and "02-3774-8013" in body

    def test_대기가_없으면_안내한다(self, store, tickets):
        assert "확인할 요청이 없" in call("#확인", store, tickets)

    def test_두_번_확인해도_하나만_만든다(self, store, tickets):
        self._submit(store, tickets)
        call("#확인", store, tickets)
        call("#확인", store, tickets)
        assert len(tickets.created) == 1

    def test_생성_직후_완료_감지에_등록한다(self, store, tickets):
        # 첫 폴링 전에 완료되면 통보가 누락된다
        seen = []
        self._submit(store, tickets, on_created=seen.append)
        call("#확인", store, tickets, on_created=seen.append)
        assert len(seen) == 1


class TestCancel:
    def test_취소하면_만들지_않는다(self, store, tickets):
        call(f"#기술정보\n{FILLED}", store, tickets)
        assert "취소했습니다" in call("#취소", store, tickets)
        assert "확인할 요청이 없" in call("#확인", store, tickets)
        assert tickets.created == []

    def test_취소할_게_없으면_그렇게_말한다(self, store, tickets):
        assert "취소할 요청이 없" in call("#취소", store, tickets)


class TestIsolation:
    """한 방에서 여러 사람이 동시에 양식을 내도 섞이지 않는다."""

    def test_남의_확인이_내_양식을_만들지_않는다(self, store, tickets):
        call(f"#기술정보\n{FILLED}", store, tickets, user=USER)
        assert "확인할 요청이 없" in call("#확인", store, tickets, user=OTHER)
        assert tickets.created == []

    def test_각자_자기_것을_확정한다(self, store, tickets):
        call(f"#기술정보\n{FILLED}", store, tickets, user=USER)
        call(f"#기술정보\n{FILLED}", store, tickets, user=OTHER)
        call("#확인", store, tickets, user=USER)
        call("#확인", store, tickets, user=OTHER)
        assert len(tickets.created) == 2


class TestExpiry:
    def test_오래된_대기는_버린다(self, tickets):
        # 한참 뒤의 #확인이 엉뚱한 양식을 만들어 내면 안 된다
        s = PendingStore(ttl=0.0)
        call(f"#기술정보\n{FILLED}", s, tickets)
        assert "확인할 요청이 없" in call("#확인", s, tickets)
        assert tickets.created == []


class TestCrmUnavailable:
    """CRM에 못 닿아도 접수는 된다.

    커맨드 서버(ai-node)는 사내 CRM 대역에 닿지 못한다(2026-09-10 확인).
    그래도 /접수 는 동작해야 한다 — 양식에 적힌 고객명으로 넘어간다.
    """

    class _Down:
        def fetch(self, code):
            from crm.client import CrmUnavailable
            raise CrmUnavailable("CRM 연결 실패: refused")

    def test_CRM이_죽어도_확인_화면이_나온다(self, store, tickets):
        got = handle(f"#기술정보\n{FILLED}", channel=CH, user_id=USER, store=store,
                     tickets=tickets, customers=self._Down(), today=TODAY)
        assert "생성할까요" in got

    def test_양식의_고객명으로_제목을_만든다(self, store, tickets):
        got = handle(f"#기술정보\n{FILLED}", channel=CH, user_id=USER, store=store,
                     tickets=tickets, customers=self._Down(), today=TODAY)
        assert "미래에셋자산운용" in got      # 양식에 적힌 값

    def test_고객명도_없으면_유형만으로_제목을_만든다(self, store, tickets):
        bare = "이전요청서\n[기본정보]\n고객번호 : E120452\n[요청정보]\n메모 : 확인"
        handle(f"#기술정보\n{bare}", channel=CH, user_id=USER, store=store,
               tickets=tickets, customers=self._Down(), today=TODAY)
        got = handle("#확인", channel=CH, user_id=USER, store=store, tickets=tickets)
        assert "접수되었습니다" in got and tickets.created[0][0].startswith("장비/설비 이전")

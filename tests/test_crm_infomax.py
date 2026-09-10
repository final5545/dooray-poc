"""사내 CRM 실 API 어댑터.

2026-09-10 실측으로 확인한 규약을 고정한다:

    없는 고객번호   →  200 · responseCode 0 · response []      (404가 아니다)
    대소문자        →  무관
    여러 건         →  info 에 여러 개 → 한 번에
    빈 info         →  ⚠️ responseCode -1 인데 전체 목록이 돌아온다
"""
import json

import pytest
import requests

from crm.client import CrmUnavailable
from crm.infomax import (
    InfomaxCrmRepository,
    join_address,
    split_contact_type,
    to_internal,
)

ROW = {
    "accountNm": "연합인포맥스",
    "custNo": "E120452",
    "addressName": "연합인포맥스 경영지원본부",
    "contactNm": "박청호",
    "contactType": "무료(고객기기)",
    "telephone": "02-398-5222",
    "address": "서울 종로구 율곡로2길 25 (수송동)",
    "addressDetail": "10층",
    "etc": "연합인포맥스",
}


class TestContactType:
    """고객구분과 기기가 한 칸에 들어온다."""

    def test_괄호를_기준으로_쪼갠다(self):
        assert split_contact_type("무료(고객기기)") == ("무료", "고객기기")

    def test_전각_괄호도_받는다(self):
        assert split_contact_type("계약（연합기기）") == ("계약", "연합기기")

    def test_괄호가_없으면_구분만(self):
        assert split_contact_type("해지") == ("해지", None)

    def test_공백은_털어낸다(self):
        assert split_contact_type("  무료 ( 고객기기 ) ") == ("무료", "고객기기")

    def test_빈_값(self):
        assert split_contact_type("") == (None, None)
        assert split_contact_type(None) == (None, None)
        assert split_contact_type("   ") == (None, None)


class TestAddress:
    def test_상세주소까지_한_줄로(self):
        assert join_address(ROW) == "서울 종로구 율곡로2길 25 (수송동) 10층"

    def test_상세가_없어도_된다(self):
        assert join_address({"address": "서울 종로구"}) == "서울 종로구"

    def test_둘_다_없으면_None(self):
        assert join_address({}) is None
        assert join_address({"address": "", "addressDetail": "  "}) is None


class TestToInternal:
    def test_필드를_내부_표준_키로_옮긴다(self):
        got = to_internal(ROW)
        assert got["code"] == "E120452"
        assert got["name"] == "연합인포맥스"
        assert got["dept"] == "연합인포맥스 경영지원본부"
        assert got["manager"] == "박청호"
        assert got["phone_office"] == "02-398-5222"
        assert got["note"] == "연합인포맥스"

    def test_고객구분과_기기가_갈린다(self):
        got = to_internal(ROW)
        assert got["customer_type"] == "무료" and got["device"] == "고객기기"

    def test_값이_없는_항목은_넣지_않는다(self):
        # 포매터가 '키 없음'과 '빈 문자열'을 같게 처리하므로 안전하다
        got = to_internal({"custNo": "E1", "accountNm": "", "telephone": None})
        assert got == {"code": "E1"}

    def test_API가_주지_않는_필드는_없다(self):
        # 계약정보·설치정보·이메일이 실 API 응답에 없다는 사실을 고정한다.
        # 나중에 CRM이 이 필드를 주기 시작하면 이 테스트가 깨져서 알게 된다.
        got = to_internal(ROW)
        for absent in ("email", "contract_start", "contract_end",
                       "billing_date", "install_date", "carrier"):
            assert absent not in got


class _Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class _Session:
    """호출을 기록하는 가짜 세션."""

    def __init__(self, resp):
        self.resp, self.calls = resp, []
        self.headers = {}

    def post(self, url, json=None, timeout=None):
        self.calls.append(json)
        if isinstance(self.resp, Exception):
            raise self.resp
        return self.resp


@pytest.fixture
def repo():
    return InfomaxCrmRepository("http://crm.invalid:8001")


def _wire(repo, body, status=200):
    repo._session = _Session(_Resp(body, status))
    return repo._session


class TestFetch:
    def test_단건_조회(self, repo):
        _wire(repo, {"responseCode": 0, "response": [ROW]})
        assert repo.fetch("e120452")["name"] == "연합인포맥스"

    def test_요청_형식은_info_배열(self, repo):
        s = _wire(repo, {"responseCode": 0, "response": [ROW]})
        repo.fetch("e120452")
        assert s.calls[0] == {"info": [{"UserId": "e120452"}]}

    def test_미등록은_None(self, repo):
        # 404가 아니라 빈 배열로 온다
        _wire(repo, {"responseCode": 0, "response": []})
        assert repo.fetch("E999999") is None

    def test_빈_고객번호는_아예_보내지_않는다(self, repo):
        # ⚠️ 빈 info 를 보내면 CRM이 전체 목록을 돌려준다(실측).
        #    호출자 실수로 고객 목록이 새면 안 된다.
        s = _wire(repo, {"responseCode": -1, "response": [ROW] * 28})
        assert repo.fetch("") is None
        assert repo.fetch("   ") is None
        assert repo.fetch(None) is None
        assert s.calls == []          # 요청 자체가 나가지 않았다


class TestFetchMany:
    def test_한_번에_묶어_보낸다(self, repo):
        s = _wire(repo, {"responseCode": 0, "response": [ROW]})
        repo.fetch_many(["E1", "E2", "E3"])
        assert len(s.calls) == 1
        assert s.calls[0]["info"] == [{"UserId": "E1"}, {"UserId": "E2"}, {"UserId": "E3"}]

    def test_고객번호로_되짚는다(self, repo):
        # 응답이 요청 순서를 지킨다는 보장이 없다
        other = {**ROW, "custNo": "E200105", "accountNm": "비엔케이자산운용"}
        _wire(repo, {"responseCode": 0, "response": [other, ROW]})
        got = repo.fetch_many(["E120452", "E200105"])
        assert got["E120452"]["name"] == "연합인포맥스"
        assert got["E200105"]["name"] == "비엔케이자산운용"

    def test_미등록은_결과에_없다(self, repo):
        _wire(repo, {"responseCode": 0, "response": [ROW]})
        got = repo.fetch_many(["E120452", "E999999"])
        assert set(got) == {"E120452"}

    def test_빈_목록은_보내지_않는다(self, repo):
        s = _wire(repo, {"responseCode": -1, "response": [ROW] * 28})
        assert repo.fetch_many([]) == {}
        assert repo.fetch_many(["", None]) == {}
        assert s.calls == []


class TestFailure:
    """조회 실패와 '없는 고객'을 구분해야 사용자에게 다른 말을 할 수 있다."""

    def test_타임아웃(self, repo):
        repo._session = _Session(requests.Timeout("timed out"))
        with pytest.raises(CrmUnavailable, match="지연"):
            repo.fetch("E1")

    def test_연결_실패(self, repo):
        repo._session = _Session(requests.ConnectionError("refused"))
        with pytest.raises(CrmUnavailable, match="연결"):
            repo.fetch("E1")

    def test_HTTP_오류(self, repo):
        _wire(repo, {}, status=500)
        with pytest.raises(CrmUnavailable, match="500"):
            repo.fetch("E1")

    def test_JSON이_아님(self, repo):
        _wire(repo, "<html>error</html>")
        with pytest.raises(CrmUnavailable, match="JSON"):
            repo.fetch("E1")

    def test_responseCode가_0이_아니면_실패로_본다(self, repo):
        # -1 인데도 데이터가 딸려 오는 경우가 있다. 쓰지 않는다.
        _wire(repo, {"responseCode": -1, "response": [ROW] * 28})
        with pytest.raises(CrmUnavailable, match="responseCode"):
            repo.fetch("E1")

    def test_response가_배열이_아니어도_깨지지_않는다(self, repo):
        _wire(repo, {"responseCode": 0, "response": None})
        assert repo.fetch("E1") is None

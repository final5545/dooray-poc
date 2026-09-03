"""CRM HTTP 어댑터 — 스펙 확정 전 골격 검증.

실제 엔드포인트가 없으므로 requests 계층을 대역으로 바꿔 확인한다.
스펙이 오면 url_template / field_map / 인증 헤더 셋만 고치면 된다.
"""
import datetime as dt

import pytest
import requests

from crm.client import (
    DEFAULT_FIELD_MAP,
    CrmUnavailable,
    HttpCustomerRepository,
    dig,
    to_internal,
)
from crm.service import handle_message

RAW = {
    "custNo": "E230096",
    "custType": "계약",
    "custName": "미래에셋자산운용",
    "deptName": "채권운용부문 투자전략본부",
    "userName": "정상호 매니저",
    "tel1": "02-3774-8013",
    "tel2": None,
    "email": "sanghojeong9210@miraeasset.com",
    "contractEndDate": "2024-04-30",
}


class FakeResponse:
    def __init__(self, status=200, payload=None, text_body=None):
        self.status_code = status
        self._payload = payload
        self._text = text_body

    def json(self):
        if self._text is not None:
            raise ValueError("not json")
        return self._payload


def repo_with(monkeypatch, **kw):
    r = HttpCustomerRepository("https://crm.internal.example", **kw)

    def install(response=None, exc=None):
        def fake_get(url, timeout=None):
            install.last_url = url
            install.last_timeout = timeout
            if exc:
                raise exc
            return response
        monkeypatch.setattr(r._session, "get", fake_get)
    r.install = install
    return r


class TestDig:
    def test_평면_경로(self):
        assert dig({"a": 1}, "a") == 1

    def test_중첩_경로(self):
        assert dig({"a": {"b": {"c": 3}}}, "a.b.c") == 3

    def test_없으면_None(self):
        assert dig({"a": 1}, "b") is None
        assert dig({"a": 1}, "a.b") is None

    def test_dict가_아니면_None(self):
        assert dig("문자열", "a") is None
        assert dig(None, "a") is None


class TestToInternal:
    def test_기본_매핑(self):
        got = to_internal(RAW)
        assert got["code"] == "E230096"
        assert got["name"] == "미래에셋자산운용"
        assert got["phone_office"] == "02-3774-8013"

    def test_값이_없으면_키를_넣지_않는다(self):
        got = to_internal(RAW)
        assert "phone_mobile" not in got     # tel2 가 None
        assert "carrier" not in got          # 응답에 아예 없음

    def test_매핑을_갈아끼울_수_있다(self):
        # 스펙이 확정되면 이 표만 고친다
        got = to_internal({"고객명": "테스트"}, {"name": "고객명"})
        assert got == {"name": "테스트"}

    def test_중첩_응답도_받는다(self):
        got = to_internal({"user": {"mail": "a@b.com"}}, {"email": "user.mail"})
        assert got["email"] == "a@b.com"


class TestFetch:
    def test_정상_조회(self, monkeypatch):
        r = repo_with(monkeypatch)
        r.install(FakeResponse(200, RAW))
        got = r.fetch("E230096")
        assert got["name"] == "미래에셋자산운용"
        assert r.install.last_url.endswith("/customers/E230096")

    def test_타임아웃_예산이_적용된다(self, monkeypatch):
        # 기획서 3초 요건 - 메신저 왕복 0.45초 = 약 2.5초
        r = repo_with(monkeypatch)
        r.install(FakeResponse(200, RAW))
        r.fetch("E230096")
        assert r.install.last_timeout == 2.5

    def test_404는_미등록(self, monkeypatch):
        r = repo_with(monkeypatch)
        r.install(FakeResponse(404))
        assert r.fetch("E999999") is None

    def test_타임아웃은_CrmUnavailable(self, monkeypatch):
        r = repo_with(monkeypatch)
        r.install(exc=requests.Timeout())
        with pytest.raises(CrmUnavailable, match="지연"):
            r.fetch("E230096")

    def test_연결오류는_CrmUnavailable(self, monkeypatch):
        r = repo_with(monkeypatch)
        r.install(exc=requests.ConnectionError("refused"))
        with pytest.raises(CrmUnavailable):
            r.fetch("E230096")

    def test_5xx는_CrmUnavailable(self, monkeypatch):
        r = repo_with(monkeypatch)
        r.install(FakeResponse(500))
        with pytest.raises(CrmUnavailable, match="500"):
            r.fetch("E230096")

    def test_JSON이_아니면_CrmUnavailable(self, monkeypatch):
        r = repo_with(monkeypatch)
        r.install(FakeResponse(200, text_body="<html>"))
        with pytest.raises(CrmUnavailable):
            r.fetch("E230096")

    def test_래핑된_응답(self, monkeypatch):
        r = repo_with(monkeypatch, result_path="result")
        r.install(FakeResponse(200, {"result": RAW}))
        assert r.fetch("E230096")["name"] == "미래에셋자산운용"

    def test_목록으로_오면_첫_건(self, monkeypatch):
        r = repo_with(monkeypatch, result_path="result")
        r.install(FakeResponse(200, {"result": [RAW]}))
        assert r.fetch("E230096")["code"] == "E230096"

    def test_빈_결과는_None(self, monkeypatch):
        r = repo_with(monkeypatch, result_path="result")
        r.install(FakeResponse(200, {"result": []}))
        assert r.fetch("E230096") is None

    def test_URL_템플릿을_바꿀_수_있다(self, monkeypatch):
        r = repo_with(monkeypatch, url_template="{base}/api/v1/cust?no={code}")
        r.install(FakeResponse(200, RAW))
        r.fetch("E230096")
        assert r.install.last_url.endswith("/api/v1/cust?no=E230096")


class TestServiceIntegration:
    """사용자에게 보이는 메시지가 상황별로 달라지는지."""

    def _repo(self, monkeypatch, **kw):
        r = repo_with(monkeypatch)
        r.install(**kw)
        return r

    def test_조회_성공(self, monkeypatch):
        got = handle_message("고객정보#E230096", self._repo(monkeypatch, response=FakeResponse(200, RAW)))
        assert "미래에셋자산운용" in got

    def test_미등록은_찾을_수_없다고_알린다(self, monkeypatch):
        got = handle_message("E999999", self._repo(monkeypatch, response=FakeResponse(404)))
        assert "등록되지 않은" in got

    def test_CRM_장애는_다른_문구로_알린다(self, monkeypatch):
        # '없는 고객'과 '지금 조회가 안 됨'은 사용자에게 다른 상황이다
        got = handle_message("E230096", self._repo(monkeypatch, exc=requests.Timeout()))
        assert "조회할 수 없습니다" in got
        assert "등록되지 않은" not in got

    def test_내부_오류를_노출하지_않는다(self, monkeypatch):
        got = handle_message("E230096", self._repo(monkeypatch, exc=requests.ConnectionError("10.1.2.3:8080 refused")))
        assert "10.1.2.3" not in got
        assert "Traceback" not in got

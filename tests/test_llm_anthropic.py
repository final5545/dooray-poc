"""AnthropicExtractor의 실패 처리 — 인증 실패 시 회로 차단 여부."""
import anthropic
import httpx2 as httpx
import pytest

from support.extractor import extract
from support.llm import Enrichment
from support.llm_anthropic import AnthropicExtractor

TEXT = "E230096 층내 이전 요청"


def _status_error(cls, status: int):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status, request=request)
    return cls("boom", response=response, body=None)


@pytest.fixture
def ext(monkeypatch):
    e = AnthropicExtractor(api_key="test-key")
    return e


def _install(monkeypatch, ext, exc):
    calls = {"n": 0}

    def fake_create(**kwargs):
        calls["n"] += 1
        raise exc

    monkeypatch.setattr(ext._client.messages, "create", fake_create)
    return calls


class TestCircuitBreaker:
    def test_인증_실패시_이후_호출을_차단한다(self, monkeypatch, ext):
        # 401은 재시도해도 낫지 않는다 → 매 메시지마다 API를 두드리면 안 된다
        calls = _install(monkeypatch, ext,
                         _status_error(anthropic.AuthenticationError, 401))
        base = extract(TEXT)

        assert ext.enrich(TEXT, base) == Enrichment()
        assert ext.enrich(TEXT, base) == Enrichment()
        assert ext.enrich(TEXT, base) == Enrichment()
        assert calls["n"] == 1, "인증 실패 후에도 API를 다시 호출했다"

    def test_권한_오류도_차단한다(self, monkeypatch, ext):
        calls = _install(monkeypatch, ext,
                         _status_error(anthropic.PermissionDeniedError, 403))
        base = extract(TEXT)
        ext.enrich(TEXT, base)
        ext.enrich(TEXT, base)
        assert calls["n"] == 1

    def test_모델_없음도_차단한다(self, monkeypatch, ext):
        calls = _install(monkeypatch, ext,
                         _status_error(anthropic.NotFoundError, 404))
        base = extract(TEXT)
        ext.enrich(TEXT, base)
        ext.enrich(TEXT, base)
        assert calls["n"] == 1


class TestTransientErrors:
    def test_레이트리밋은_다음_메시지에서_재시도한다(self, monkeypatch, ext):
        # 429는 일시적이므로 차단하면 안 된다
        calls = _install(monkeypatch, ext,
                         _status_error(anthropic.RateLimitError, 429))
        base = extract(TEXT)
        ext.enrich(TEXT, base)
        ext.enrich(TEXT, base)
        assert calls["n"] == 2

    def test_서버_오류도_재시도한다(self, monkeypatch, ext):
        calls = _install(monkeypatch, ext,
                         _status_error(anthropic.InternalServerError, 500))
        base = extract(TEXT)
        ext.enrich(TEXT, base)
        ext.enrich(TEXT, base)
        assert calls["n"] == 2

    def test_네트워크_오류도_재시도한다(self, monkeypatch, ext):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        calls = _install(monkeypatch, ext,
                         anthropic.APIConnectionError(request=request))
        base = extract(TEXT)
        ext.enrich(TEXT, base)
        ext.enrich(TEXT, base)
        assert calls["n"] == 2

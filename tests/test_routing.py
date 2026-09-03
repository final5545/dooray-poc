import pytest

from routing import RouteConfigError, parse_routes


class TestParseRoutes:
    def test_단일(self):
        assert parse_routes("111:crm") == {"111": "crm"}

    def test_복수(self):
        assert parse_routes("111:crm,222:support") == {"111": "crm", "222": "support"}

    def test_공백_허용(self):
        assert parse_routes(" 111 : crm , 222 : support ") == {"111": "crm", "222": "support"}

    def test_빈_값은_빈_dict(self):
        # 안전한 기본값 — 아무 채널도 처리하지 않는다
        assert parse_routes("") == {}
        assert parse_routes(None) == {}
        assert parse_routes(",, ,") == {}

    def test_같은_핸들러_중복은_허용(self):
        assert parse_routes("111:crm,111:crm") == {"111": "crm"}


class TestErrors:
    def test_콜론_없음(self):
        with pytest.raises(RouteConfigError, match="형식"):
            parse_routes("111")

    def test_알_수_없는_핸들러(self):
        with pytest.raises(RouteConfigError, match="알 수 없는"):
            parse_routes("111:unknown")

    def test_채널ID_비어있음(self):
        with pytest.raises(RouteConfigError, match="비어"):
            parse_routes(":crm")

    def test_한_채널에_다른_핸들러_중복(self):
        with pytest.raises(RouteConfigError, match="중복"):
            parse_routes("111:crm,111:support")

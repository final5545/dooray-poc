import datetime as dt

from support.extractor import extract
from support.llm import Enrichment, NullExtractor, parse_enrichment

TODAY = dt.date(2026, 9, 2)


class TestParseEnrichment:
    def test_정상_JSON(self):
        got = parse_enrichment(
            '{"customer_name": "비엔케이자산운용", "request_type": "장비/설비 이전",'
            ' "detail": "층내 이전", "contact": "김수빈 파트너"}'
        )
        assert got.customer_name == "비엔케이자산운용"
        assert got.request_type == "장비/설비 이전"
        assert got.detail == "층내 이전"

    def test_코드펜스가_붙어도_파싱(self):
        got = parse_enrichment('```json\n{"customer_name": "한국거래소"}\n```')
        assert got.customer_name == "한국거래소"

    def test_앞뒤_설명이_붙어도_JSON만_뽑는다(self):
        got = parse_enrichment('다음과 같습니다:\n{"customer_name": "에이치라인해운"}\n이상입니다.')
        assert got.customer_name == "에이치라인해운"

    def test_정의_밖_유형은_버린다(self):
        # 분류 체계에 없는 값을 모델이 만들어내면 채택하지 않는다
        got = parse_enrichment('{"request_type": "기타요청"}')
        assert got.request_type is None

    def test_null과_빈_문자열은_None(self):
        got = parse_enrichment('{"customer_name": null, "detail": "   ", "contact": ""}')
        assert got.customer_name is None
        assert got.detail is None
        assert got.contact is None

    def test_깨진_JSON은_빈_값(self):
        for bad in ("", "not json", "{broken", None):
            got = parse_enrichment(bad)
            assert got == Enrichment()


class TestNullExtractor:
    def test_아무것도_보강하지_않는다(self):
        req = extract("E230096 신규설치", TODAY)
        assert NullExtractor().enrich("E230096 신규설치", req) == Enrichment()

import datetime as dt

from support.extractor import (
    extract,
    extract_desired_date,
    extract_request_type,
)

TODAY = dt.date(2026, 8, 1)

# 기술지원 기획서 §5 화면 출력 예시의 실제 요청문 형태
CASE_1 = """E140605 에이치라인해운 자금기획팀
1882 엑셀 2016버전 업그레이드 부탁"""

CASE_2 = """비엔케이자산운용
E21016, E200105 층내 이전 요청으로 부탁드립니다.
희망일정 : 8월 28일(금) 오후 4시 이후
담당자 : 김수빈 파트너 010-6265-4782"""

CASE_3 = """한국거래소 파생시장부(부산) 윈도우데이트부탁드립니다.
김재영 차장: E050282 051-662-2635
최재원 대리: E050102
이현석 수석: E050345"""


class TestRequestType:
    def test_업그레이드(self):
        assert extract_request_type(CASE_1) == "SW 업그레이드"

    def test_층내_이전(self):
        assert extract_request_type(CASE_2) == "장비/설비 이전"

    def test_윈도우_오타도_인식(self):
        # 원문이 '윈도우데이트'(업 누락)라 '윈도우' 키워드로 잡는다
        assert extract_request_type(CASE_3) == "SW 업그레이드"

    def test_유형_없음(self):
        assert extract_request_type("안녕하세요") is None

    def test_빈_입력(self):
        assert extract_request_type("") is None
        assert extract_request_type(None) is None


class TestDesiredDate:
    def test_라벨_있는_한글_날짜(self):
        date, raw = extract_desired_date(CASE_2, TODAY)
        assert date == dt.date(2026, 8, 28)
        assert "8월 28일" in raw

    def test_슬래시_형식(self):
        date, _ = extract_desired_date("방문 8/14 예정", TODAY)
        assert date == dt.date(2026, 8, 14)

    def test_ISO_형식(self):
        date, _ = extract_desired_date("희망일 2026-09-15", TODAY)
        assert date == dt.date(2026, 9, 15)

    def test_지난_날짜는_내년으로_해석(self):
        # 8월 기준 1월은 이미 지났으므로 내년으로 본다
        date, _ = extract_desired_date("1월 5일 방문", TODAY)
        assert date == dt.date(2027, 1, 5)

    def test_유효하지_않은_날짜(self):
        date, _ = extract_desired_date("2월 30일", TODAY)
        assert date is None

    def test_날짜_없음(self):
        assert extract_desired_date("업그레이드 부탁", TODAY) == (None, None)


class TestExtract:
    def test_케이스1(self):
        got = extract(CASE_1, TODAY)
        assert got.customer_codes == ["E140605"]
        assert got.request_type == "SW 업그레이드"
        assert got.desired_date is None
        assert got.is_actionable

    def test_케이스2_복수_고객번호(self):
        got = extract(CASE_2, TODAY)
        assert got.customer_codes == ["E21016", "E200105"]
        assert got.request_type == "장비/설비 이전"
        assert got.desired_date == dt.date(2026, 8, 28)

    def test_케이스3_3건(self):
        got = extract(CASE_3, TODAY)
        assert got.customer_codes == ["E050282", "E050102", "E050345"]
        assert got.request_type == "SW 업그레이드"

    def test_고객번호가_없으면_처리대상이_아니다(self):
        got = extract("오늘 점심 뭐 먹죠", TODAY)
        assert not got.is_actionable
        assert got.customer_codes == []

    def test_연락처를_고객번호로_오인하지_않는다(self):
        # 요청문에 섞인 연락처가 E-code로 잡히면 안 된다
        got = extract(CASE_2, TODAY)
        assert all(c.startswith("E") for c in got.customer_codes)
        assert len(got.customer_codes) == 2

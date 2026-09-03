import datetime as dt

from support.extractor import SupportRequest
from support.ticket import build_body, build_title


def req(**kw) -> SupportRequest:
    base = dict(customer_codes=["E230096"], request_type="신규설치",
                desired_date=dt.date(2026, 8, 14), desired_raw="8월 14일", raw_text="원문")
    base.update(kw)
    return SupportRequest(**base)


class TestTitle:
    def test_기획서_예시_형태(self):
        # 기획서 §2 예시: "BNK증권 신규설치 [방문예정 8/14]"
        got = build_title(req(), "BNK증권", status_label="방문예정")
        assert got == "BNK증권 신규설치 [방문예정 8/14]"

    def test_기본_상태는_접수(self):
        # AI 자동 등록 시점은 '접수'다 (기획서 §4)
        assert build_title(req(), "BNK증권") == "BNK증권 신규설치 [접수 8/14]"

    def test_희망일이_없으면_날짜를_생략(self):
        assert build_title(req(desired_date=None), "BNK증권") == "BNK증권 신규설치 [접수]"

    def test_고객사명이_없으면_유형만(self):
        assert build_title(req()) == "신규설치 [접수 8/14]"

    def test_유형도_없으면_고객번호로_대체(self):
        got = build_title(req(request_type=None))
        assert "E230096" in got

    def test_아무_정보도_없을_때(self):
        got = build_title(req(customer_codes=[], request_type=None, desired_date=None))
        assert got == "기술지원 요청 [접수]"


class TestBody:
    def test_기획서_섹션이_모두_있다(self):
        got = build_body(req(), "BNK증권")
        for key in ("[고객사]", "[고객 고유 번호(추출)]", "[요청 유형]", "[원문]"):
            assert key in got

    def test_복수_고객번호를_모두_기록(self):
        got = build_body(req(customer_codes=["E21016", "E200105"]), "비엔케이자산운용")
        assert "E21016, E200105" in got

    def test_원문을_보존한다(self):
        got = build_body(req(raw_text="층내 이전 요청"), "고객사")
        assert "층내 이전 요청" in got

    def test_빈_값은_공란으로_둔다(self):
        got = build_body(req(request_type=None), None)
        assert "[요청 유형] " in got
        assert "None" not in got

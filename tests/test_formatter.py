import re

from crm.formatter import format_customer_card, format_error, format_not_found

ROW = {
    "code": "E230096",
    "customer_type": "계약",
    "name": "미래에셋자산운용",
    "dept": "채권운용부문 투자전략본부",
    "manager": "정상호 매니저",
    "phone_office": "02-3774-8013",
    "phone_mobile": None,
    "email": "sanghojeong9210@miraeasset.com",
    "billing_date": "2023-05-01",
    "contract_start": "2023-05-01",
    "contract_end": "2024-04-30",
    "renewal_start": None,
    "install_date": "2023-02-13",
    "device": "고객기기",
    "line_type": "고객회선",
    "line_type2": "사내-LAN(고정IP)",
    "carrier": None,
}


class TestSections:
    def test_네_개_섹션이_모두_나온다(self):
        got = format_customer_card(ROW)
        for title in ("[기본정보]", "[사용자정보]", "[계약정보]", "[설치정보]"):
            assert title in got

    def test_값이_출력된다(self):
        got = format_customer_card(ROW)
        assert "미래에셋자산운용" in got and "E230096" in got and "정상호 매니저" in got


class TestNull처리:
    def test_Null은_행을_유지하고_값만_비운다(self):
        # 기획서 §4: "임의 문자 없이 '공란'으로 표시"
        got = format_customer_card(ROW)
        assert "전화2 : \n" in got + "\n"
        assert "갱신시작일 : " in got
        assert "통신사 : " in got

    def test_행을_생략하지_않는다(self):
        got = format_customer_card(ROW)
        assert "전화2" in got and "갱신시작일" in got and "통신사" in got

    def test_임의_문자로_채우지_않는다(self):
        got = format_customer_card(ROW)
        for filler in ("N/A", "없음", "-", "null", "None"):
            assert f"전화2 : {filler}" not in got


class TestMasking:
    def test_기본값은_노출(self):
        # PoC 결정(2026-09-02): 기획서 §5 원안대로 마스킹 없이 노출.
        # 운영 전환 전 보안팀 협의 필요.
        got = format_customer_card(ROW)
        assert "02-3774-8013" in got
        assert "sanghojeong9210@miraeasset.com" in got

    def test_마스킹을_켤_수_있다(self):
        got = format_customer_card(ROW, mask=True)
        assert "02-3774-8013" not in got
        assert "sanghojeong9210@" not in got
        assert "02-****-8013" in got

    def test_마스킹시에도_이름_부서는_보존된다(self):
        got = format_customer_card(ROW, mask=True)
        assert "정상호 매니저" in got
        assert "채권운용부문 투자전략본부" in got

    def test_환경변수로_기본값을_바꿀_수_있다(self, monkeypatch):
        import importlib

        import crm.formatter as fmt
        monkeypatch.setenv("CRM_MASK", "1")
        importlib.reload(fmt)
        try:
            assert "02-****-8013" in fmt.format_customer_card(ROW)
        finally:
            monkeypatch.delenv("CRM_MASK")
            importlib.reload(fmt)


class TestRendering:
    def test_마크다운_문법을_쓰지_않는다(self):
        # Dooray 메신저는 표/굵게/취소선을 렌더링하지 않는다 (06 §7).
        # 마스킹의 '*'는 마크다운 강조가 아니다 — 굵게는 **내용** 형태여야 한다.
        got = format_customer_card(ROW)
        assert "|" not in got, "표 문법은 파이프가 그대로 노출된다"
        assert "~~" not in got
        assert not re.search(r"\*\*\S.*?\*\*", got), "굵게 문법이 섞였다"

    def test_빈_입력(self):
        assert format_customer_card({}) == "조회 결과가 없습니다."
        assert format_customer_card(None) == "조회 결과가 없습니다."


class TestOtherFormats:
    def test_미조회(self):
        assert "E999999" in format_not_found("E999999")

    def test_오류_메시지에_내부정보가_없다(self):
        got = format_error()
        assert "Traceback" not in got and "Exception" not in got

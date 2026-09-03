from crm.masking import mask_email, mask_phone, mask_text


class TestMaskEmail:
    def test_로컬파트_앞_두자만_남긴다(self):
        assert mask_email("sanghojeong9210@miraeasset.com") == "sa****@miraeasset.com"

    def test_도메인은_보존한다(self):
        assert "@miraeasset.com" in mask_email("a.b@miraeasset.com")

    def test_짧은_로컬파트(self):
        assert mask_email("ab@x.com") == "a****@x.com"

    def test_문장_안에_섞인_경우(self):
        got = mask_email("담당자 hong@infomax.co.kr 입니다")
        assert "hong@" not in got and "ho****@infomax.co.kr" in got


class TestMaskPhone:
    def test_휴대폰(self):
        assert mask_phone("010-1234-5678") == "010-****-5678"

    def test_서울_유선_내선(self):
        # 기획서 전화1(내선) 실제 예시
        assert mask_phone("02-3774-8013") == "02-****-8013"

    def test_지역_유선(self):
        # 기술지원 기획서 예시 (051-662-2635)
        assert mask_phone("051-662-2635") == "051-****-2635"

    def test_하이픈_없는_형식(self):
        assert mask_phone("01012345678") == "010-****-5678"

    def test_공백_구분(self):
        assert mask_phone("010 1234 5678") == "010-****-5678"

    def test_날짜와_충돌하지_않는다(self):
        # 계약정보는 YYYY-MM-DD 포맷이다
        for date in ("2023-05-01", "2024-04-30", "2023-02-13"):
            assert mask_phone(date) == date


class TestMaskText:
    def test_이메일과_전화_동시_처리(self):
        got = mask_text("정상호 매니저 02-3774-8013 sanghojeong9210@miraeasset.com")
        assert "3774" not in got
        assert "sanghojeong9210@" not in got
        assert "정상호 매니저" in got   # 이름은 그대로 둔다

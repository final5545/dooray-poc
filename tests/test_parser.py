from crm.parser import has_lookup_prefix, parse_all_customer_codes, parse_customer_code


class TestParseCustomerCode:
    def test_6자리(self):
        assert parse_customer_code("E230096") == "E230096"

    def test_5자리(self):
        # 기술지원 기획서 화면 예시의 실제 값 (E21016)
        assert parse_customer_code("E21016") == "E21016"

    def test_명령어_형태(self):
        # CRM 기획서 §5 화면 예시: "고객정보#E230096"
        assert parse_customer_code("고객정보#E230096") == "E230096"

    def test_문장_안에_섞인_경우(self):
        assert parse_customer_code("E140605 에이치라인해운 자금기획팀") == "E140605"

    def test_소문자_정규화(self):
        assert parse_customer_code("e230096") == "E230096"

    def test_대상_아님(self):
        for text in ["안녕하세요", "", "회의 3시에 합시다"]:
            assert parse_customer_code(text) is None

    def test_None_입력(self):
        assert parse_customer_code(None) is None

    def test_자릿수_범위_밖(self):
        assert parse_customer_code("E2301") is None       # 4자리
        assert parse_customer_code("E23009611") is None   # 8자리

    def test_단어_경계(self):
        assert parse_customer_code("XE230096X") is None


class TestPrefix:
    def test_프리픽스_인식(self):
        assert has_lookup_prefix("고객정보#E230096")
        assert has_lookup_prefix("고객 정보 E230096")
        assert not has_lookup_prefix("E230096")

    def test_프리픽스_강제_모드(self):
        assert parse_customer_code("고객정보#E230096", require_prefix=True) == "E230096"
        assert parse_customer_code("E230096", require_prefix=True) is None


class TestParseAll:
    def test_복수_추출(self):
        # 기술지원 기획서: "E21016, E200105 층내 이전 요청"
        assert parse_all_customer_codes("E21016, E200105 층내 이전") == ["E21016", "E200105"]

    def test_3건_이상(self):
        got = parse_all_customer_codes("김재영 E050282 최재원 E050102 이현석 E050345")
        assert got == ["E050282", "E050102", "E050345"]

    def test_중복은_한_번만(self):
        assert parse_all_customer_codes("E230096 E230096") == ["E230096"]

    def test_없으면_빈_리스트(self):
        assert parse_all_customer_codes("없음") == []

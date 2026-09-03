"""요청서 양식 — 빈 양식 배포와 채워진 양식 해석."""
import datetime as dt

from support.form import (
    CANCEL,
    CONFIRM,
    SUBMIT,
    build_form,
    build_list,
    build_preview,
    looks_like_form,
    parse_command,
    parse_form,
    pick_form,
    to_request,
)

TODAY = dt.date(2026, 9, 3)

FILLED = """이전요청서
[기본정보]
고객번호 : E230096
고객명 : 미래에셋자산운용 채권운용본부 투자전략운용부 정상호 매니저
[요청정보]
희망일시 : 2026년 8월 30일 오후 4시 이후
연락처 : 정상호 매니저 02-3774-8013
메모 : 이전 간 모니터 2대 추가"""


class TestParseCommand:
    def test_명령과_본문을_가른다(self):
        assert parse_command(f"#{SUBMIT}\n첫 줄\n둘째 줄") == (SUBMIT, "첫 줄\n둘째 줄")

    def test_본문이_없어도_된다(self):
        assert parse_command("#이전") == ("이전", "")

    def test_앞뒤_공백은_무시(self):
        assert parse_command("  #이전  \n") == ("이전", "")

    def test_명령이_아니면_None(self):
        # CRM 조회 방의 일반 메시지를 삼키면 안 된다
        assert parse_command("E230096 계약 언제 끝나지?") is None
        assert parse_command("") is None
        assert parse_command(None) is None

    def test_본문_중간의_샵은_명령이_아니다(self):
        assert parse_command("고객이 #이전 이라고 했어요") is None


class TestBuildForm:
    def test_제목과_항목이_모두_나온다(self):
        got = build_form("이전")
        assert got.startswith("이전요청서")
        for label in ("고객번호", "고객명", "희망일시", "연락처", "메모"):
            assert f"{label} : " in got

    def test_섹션_머리는_콜론이_없다(self):
        got = build_form("이전")
        assert "[기본정보]\n" in got and "[기본정보] :" not in got

    def test_유형마다_제목이_다르다(self):
        assert build_form("장애").startswith("장애신고서")
        assert build_form("교체").startswith("노후교체요청서")

    def test_모르는_양식은_None(self):
        assert build_form("점심") is None

    def test_안내에_제출_방법이_있다(self):
        assert f"#{SUBMIT}" in build_list() and "#이전" in build_list()


class TestParseForm:
    def test_채운_양식을_읽는다(self):
        d = parse_form(FILLED)
        assert d.code == "E230096"
        assert d.request_type == "장비/설비 이전"
        assert d.contact == "정상호 매니저 02-3774-8013"
        assert d.memo == "이전 간 모니터 2대 추가"

    def test_고객명은_적힌_그대로_둔다(self):
        # 부서·담당자가 섞여 있어도 버리지 않는다. 제목에는 CRM 값을 쓴다
        assert "투자전략운용부" in parse_form(FILLED).customer_name

    def test_빈_칸은_없는_것으로_본다(self):
        d = parse_form("이전요청서\n고객번호 : E230096\n메모 : ")
        assert d.code == "E230096" and d.memo is None

    def test_전각_콜론도_받는다(self):
        assert parse_form("이전요청서\n고객번호 ： E230096").code == "E230096"

    def test_공백이_흔들려도_읽는다(self):
        assert parse_form("이전요청서\n  고객번호:E230096  ").code == "E230096"

    def test_고객번호_칸이_비면_본문에서_줍는다(self):
        d = parse_form("이전요청서\n고객번호 : \n메모 : E230096 건입니다")
        assert d.code == "E230096"

    def test_고객번호_칸에_잡담이_섞여도_번호만_쓴다(self):
        assert parse_form("이전요청서\n고객번호 : E230096 (미래에셋)").code == "E230096"

    def test_고객번호가_없으면_유효하지_않다(self):
        assert not parse_form("이전요청서\n메모 : 급합니다").is_valid

    def test_제목이_없으면_유형도_없다(self):
        # 유형을 못 정해도 티켓은 만들 수 있다. 제목만 고객명으로 간다
        d = parse_form("고객번호 : E230096")
        assert d.is_valid and d.request_type is None

    def test_모르는_라벨은_버린다(self):
        d = parse_form("이전요청서\n고객번호 : E230096\n결재자 : 김부장")
        assert d.code == "E230096"


class TestToRequest:
    def test_희망일시를_날짜로_바꾼다(self):
        req = to_request(parse_form(FILLED), TODAY)
        assert req.desired_date == dt.date(2026, 8, 30)

    def test_원문_표현을_남긴다(self):
        # "오후 4시 이후" 같은 정보는 날짜만으로 사라진다
        assert "오후 4시" in to_request(parse_form(FILLED), TODAY).desired_raw

    def test_유형과_고객번호가_넘어간다(self):
        req = to_request(parse_form(FILLED), TODAY)
        assert req.customer_codes == ["E230096"]
        assert req.request_type == "장비/설비 이전"

    def test_희망일시가_없어도_된다(self):
        req = to_request(parse_form("이전요청서\n고객번호 : E230096"), TODAY)
        assert req.desired_date is None and req.is_actionable


class TestPreview:
    def test_읽은_대로_보여준다(self):
        d = parse_form(FILLED)
        got = build_preview(d, "미래에셋자산운용 장비/설비 이전 [접수 8/30]", "미래에셋자산운용")
        assert "미래에셋자산운용 장비/설비 이전 [접수 8/30]" in got
        assert "E230096" in got and "모니터 2대" in got

    def test_확인과_취소_방법을_알려준다(self):
        got = build_preview(parse_form(FILLED), "제목", None)
        assert f"#{CONFIRM}" in got and f"#{CANCEL}" in got

    def test_눌러야_하는지_쳐야_하는지_분명히_한다(self):
        # 버튼처럼 보이면 눌러 보게 된다. 여기는 글자다
        got = build_preview(parse_form(FILLED), "제목", None)
        assert "입력해 주세요" in got

    def test_버튼을_쓰는_방법도_알려준다(self):
        assert "/접수" in build_preview(parse_form(FILLED), "제목", None)

    def test_빈_항목은_줄을_만들지_않는다(self):
        d = parse_form("이전요청서\n고객번호 : E230096")
        got = build_preview(d, "제목", None)
        assert "메모" not in got and "연락처" not in got


class TestPickForm:
    """커맨드가 방의 최근 양식을 찾아 읽는다.

    슬래시 커맨드에 여러 줄을 실을 수 없어(2026-09-03 실측) 양식은 일반
    메시지로 올리고 커맨드가 그것을 찾아온다.
    """

    def _msg(self, text, sender="u1"):
        return {"text": text,
                "sender": {"member": {"organizationMemberId": sender}}}

    def test_명령_줄을_떼고_본문만_준다(self):
        got = pick_form([self._msg(f"#{SUBMIT}\n{FILLED}")], "u1")
        assert got.startswith("이전요청서") and "#" not in got.splitlines()[0]

    def test_명령_없이_붙여넣은_양식도_찾는다(self):
        assert pick_form([self._msg(FILLED)], "u1").startswith("이전요청서")

    def test_최신_것을_고른다(self):
        old = FILLED.replace("E230096", "E140605")
        got = pick_form([self._msg(FILLED), self._msg(old)], "u1")
        assert "E230096" in got

    def test_남의_양식은_고르지_않는다(self):
        assert pick_form([self._msg(FILLED, sender="u2")], "u1") is None

    def test_사용자를_지정하지_않으면_아무거나(self):
        assert pick_form([self._msg(FILLED, sender="u2")]) is not None

    def test_잡담은_양식이_아니다(self):
        assert pick_form([self._msg("점심 뭐 먹지"),
                          self._msg("E230096 조회해줘")], "u1") is None

    def test_제목을_지운_양식도_라벨로_알아본다(self):
        body = "고객번호 : E230096\n연락처 : 02-1234-5678"
        assert pick_form([self._msg(body)], "u1") is not None

    def test_라벨_하나만으로는_양식이_아니다(self):
        # '고객번호 : E230096' 한 줄짜리 조회 요청을 양식으로 오인하면 안 된다
        assert not looks_like_form("고객번호 : E230096")

    def test_빈_입력(self):
        assert pick_form([], "u1") is None
        assert pick_form(None, "u1") is None


class TestFormCoverage:
    """기획서 §4의 요청 유형은 모두 양식이 있어야 한다.

    양식으로 접수한 건과 자유 서술로 접수한 건의 제목이 같은 어휘로 나와야
    현황판에서 한 종류로 묶인다.
    """

    def test_추출기가_아는_유형은_모두_양식이_있다(self):
        from support.extractor import REQUEST_TYPES
        from support.form import FORMS
        have = {t for _, t in FORMS.values()}
        missing = [label for label, _ in REQUEST_TYPES if label not in have]
        assert missing == [], f"양식 없는 유형: {missing}"

    def test_양식의_유형은_추출기_라벨과_같다(self):
        # 어긋나면 같은 요청이 제목에서 다른 이름으로 갈린다
        from support.extractor import REQUEST_TYPES
        from support.form import FORMS
        known = {label for label, _ in REQUEST_TYPES}
        for key, (_, request_type) in FORMS.items():
            assert request_type in known, f"#{key} 의 유형 '{request_type}' 이 낯설다"

    def test_트리거가_겹치지_않는다(self):
        from support.form import CANCEL, CONFIRM, FORMS, LIST, SUBMIT
        reserved = {SUBMIT, CONFIRM, CANCEL, LIST}
        assert not (set(FORMS) & reserved)

    def test_모든_양식이_제목과_항목을_갖춘다(self):
        from support.form import FORMS, build_form
        for key in FORMS:
            got = build_form(key)
            assert got and "고객번호 : " in got


class TestPickFormScope:
    """/접수 는 방 전체를 훑되 **내가 쓴 것만** 고른다.

    양식에는 고객 연락처가 들어 있다. 옆 사람이 올린 요청서를 내가 확정해
    버리면 안 된다.
    """

    def _msg(self, text, sender):
        return {"text": text, "sender": {"member": {"organizationMemberId": sender}}}

    def test_남의_것이_더_최근이어도_내_것을_고른다(self):
        mine = FILLED
        theirs = FILLED.replace("E230096", "E050282")
        got = pick_form([self._msg(theirs, "u2"), self._msg(mine, "u1")], "u1")
        assert "E230096" in got

    def test_내_것이_없으면_남의_것을_주지_않는다(self):
        assert pick_form([self._msg(FILLED, "u2")], "u1") is None

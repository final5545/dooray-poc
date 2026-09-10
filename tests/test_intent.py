"""조회인가 요청인가 — 자연어 접수의 판정.

CRM 조회 방에서 고객번호가 든 메시지는 두 가지 뜻을 가진다. 잘못 읽어
요청이 되면 엉뚱한 업무가 생기는데, 두레이에는 업무 삭제 API가 없다.
그래서 **확신이 없으면 조회로 눕는다**는 것이 이 모듈의 규율이다.
"""
from support.intent import (
    LOOKUP,
    REQUEST,
    Intent,
    form_title,
    might_be_request,
    parse_intent,
    to_form_text,
)


class TestGate:
    """LLM을 부를 가치가 있는 문장인가."""

    def test_요청_유형_키워드를_잡는다(self):
        assert might_be_request("E230096 이전 요청할래")
        assert might_be_request("E050282 신규설치 부탁드립니다")

    def test_키워드가_없어도_요청_어투를_잡는다(self):
        # "안 켜져요"는 장애 키워드 어디에도 없다(실측에서 놓쳤던 문장)
        assert might_be_request("E140605 단말이 안 켜져요. 급합니다")
        assert might_be_request("E200105 모니터 하나 더 필요합니다")
        assert might_be_request("E230096 자리 좀 옮겨주세요")

    def test_명백한_조회는_거른다(self):
        # 여기서 걸러지면 LLM을 아예 부르지 않는다
        assert not might_be_request("E120452")
        assert not might_be_request("E230096 담당자 누구야")
        assert not might_be_request("E230096 계약 언제 끝나지?")

    def test_빈_입력(self):
        assert not might_be_request("")
        assert not might_be_request(None)


class TestParse:
    def _raw(self, **kw):
        base = {"kind": REQUEST, "request_type": "장비/설비 이전",
                "desired": None, "contact": None, "memo": None}
        base.update(kw)
        return base

    def test_요청을_읽는다(self):
        got = parse_intent(self._raw(desired="9월 30일 오후", memo="모니터 2대 추가"))
        assert got.is_request and got.request_type == "장비/설비 이전"
        assert got.desired == "9월 30일 오후" and got.memo == "모니터 2대 추가"

    def test_조회는_요청이_아니다(self):
        assert not parse_intent(self._raw(kind=LOOKUP)).is_request

    def test_모르는_값은_조회로_눕는다(self):
        # 잘못 읽어 요청이 되는 것보다 조회가 되는 편이 낫다
        for raw in (None, {}, {"kind": "확인불가"}, {"kind": ""}, "문자열"):
            assert not parse_intent(raw).is_request

    def test_빈_문자열은_None으로_눕힌다(self):
        got = parse_intent(self._raw(desired="", contact="   ", memo="없음"))
        assert got.desired is None and got.contact is None and got.memo is None

    def test_유형을_못_정해도_요청은_요청이다(self):
        # 제목만 일반형으로 나갈 뿐 접수는 된다
        assert parse_intent(self._raw(request_type=None)).is_request


class TestToFormText:
    """사람이 손으로 채운 양식과 **같은 모양**이어야 같은 경로로 흐른다."""

    def test_양식_파서가_그대로_읽는다(self):
        from support.form import parse_form
        intent = Intent(kind=REQUEST, request_type="장비/설비 이전",
                        desired="9월 30일 오후", contact="02-3774-8013",
                        memo="모니터 2대 추가")
        text = to_form_text(intent, "E230096", "이전요청서")
        got = parse_form(text)
        assert got.code == "E230096"
        assert got.request_type == "장비/설비 이전"
        assert got.desired == "9월 30일 오후"
        assert got.memo == "모니터 2대 추가"

    def test_빈_항목은_빈_칸으로_둔다(self):
        from support.form import parse_form
        text = to_form_text(Intent(kind=REQUEST), "E230096")
        got = parse_form(text)
        assert got.code == "E230096" and got.desired is None

    def test_고객명은_비워_둔다(self):
        # CRM 조회가 채우는 편이 정확하다
        assert "고객명 : \n" in to_form_text(Intent(kind=REQUEST), "E1") + "\n"


class TestFormTitle:
    def test_유형에_맞는_제목(self):
        assert form_title("장비/설비 이전") == "이전요청서"
        assert form_title("장애") == "장애신고서"

    def test_모르는_유형은_일반_제목(self):
        assert form_title(None) == "기술지원요청서"
        assert form_title("점심 주문") == "기술지원요청서"

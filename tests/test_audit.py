"""승인 사용자 확인과 감사로그.

2026-09-10 회의 기본조건 중 둘. 채널 화이트리스트는 처음부터 있었지만
**그 방에 들어온 사람이면 누구나** 고객정보를 조회할 수 있었다. 모의
데이터일 때는 넘어갈 일이었으나 실 CRM이 붙은 이상 다르다.
"""
import json

from support.audit import (
    CREATE,
    DENIED,
    LOOKUP,
    AuditLog,
    Guard,
    parse_allowed,
)

ME = "3267267451433100066"
OTHER = "3362258975191542304"


class TestParseAllowed:
    def test_쉼표로_나눈다(self):
        assert parse_allowed(f"{ME},{OTHER}") == {ME, OTHER}

    def test_공백과_줄바꿈을_받는다(self):
        assert parse_allowed(f"  {ME} ,\n {OTHER}  ") == {ME, OTHER}

    def test_빈_값은_빈_집합(self):
        for raw in ("", "   ", None, ",,"):
            assert parse_allowed(raw) == set()


class TestGuard:
    def test_명단에_있으면_허용(self):
        g = Guard({ME, OTHER})
        assert g.permits(ME) and g.permits(OTHER)

    def test_명단에_없으면_거부(self):
        g = Guard({ME})
        assert not g.permits(OTHER)
        assert not g.permits(None)
        assert not g.permits("")

    def test_명단이_비면_제한하지_않는다(self):
        # 설정을 빠뜨렸다고 서비스를 조용히 죽이면 안 된다.
        # 켜는 것은 명시적인 선택이어야 한다.
        g = Guard(set())
        assert not g.enabled
        assert g.permits(ME) and g.permits("아무나") and g.permits(None)

    def test_상태를_배너에_찍을_수_있다(self):
        # 켜졌는지 눈으로 보여야 한다
        assert "2명" in Guard({ME, OTHER}).label
        assert "제한 없음" in Guard(set()).label


class TestAuditLog:
    def test_경로가_없으면_쓰지_않는다(self, tmp_path):
        # 단위테스트·로컬 구동에서 파일이 생기지 않게
        log = AuditLog(None)
        row = log.write(LOOKUP, user=ME, codes=["E120452"])
        assert row["event"] == LOOKUP
        assert not list(tmp_path.iterdir())

    def test_한_줄에_한_사건(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        log = AuditLog(str(path))
        log.write(LOOKUP, user=ME, channel="c1", codes=["E120452"])
        log.write(CREATE, user=ME, channel="c1", task="t1")

        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["event"] == LOOKUP and first["user"] == ME
        assert first["codes"] == ["E120452"]
        assert json.loads(lines[1])["task"] == "t1"

    def test_시각이_들어간다(self, tmp_path):
        log = AuditLog(str(tmp_path / "a.jsonl"))
        assert "at" in log.write(DENIED, user=OTHER)

    def test_값이_없는_항목은_빼고_쓴다(self, tmp_path):
        log = AuditLog(str(tmp_path / "a.jsonl"))
        row = log.write(LOOKUP, user=ME, codes=None, note=None)
        assert "codes" not in row and "note" not in row

    def test_없는_디렉터리를_만든다(self, tmp_path):
        path = tmp_path / "깊은" / "곳" / "audit.jsonl"
        AuditLog(str(path)).write(LOOKUP, user=ME)
        assert path.exists()

    def test_기록에_실패해도_예외를_던지지_않는다(self, tmp_path):
        # 감사로그 때문에 사용자 요청이 막히면 안 된다
        log = AuditLog(str(tmp_path / "a.jsonl"))
        log.path = str(tmp_path)          # 디렉터리를 파일처럼 열면 실패한다
        log.write(LOOKUP, user=ME)        # 예외가 나지 않아야 한다


class TestNoLeak:
    """⚠️ 조회 **결과**를 남기면 로그 파일이 새로운 유출 경로가 된다."""

    def test_무엇을_찾았는지만_남긴다(self, tmp_path):
        path = tmp_path / "a.jsonl"
        log = AuditLog(str(path))
        # 호출자는 고객번호만 넘긴다. 이름·연락처는 넘기지 않는다.
        log.write(LOOKUP, user=ME, channel="c1", codes=["E120452"])

        text = path.read_text(encoding="utf-8")
        assert "E120452" in text
        for leaked in ("연합인포맥스", "박청호", "02-398-5222", "종로구"):
            assert leaked not in text

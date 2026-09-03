import pytest

from crm.client import FakeCustomerRepository
from crm.service import handle_message


@pytest.fixture
def repo():
    return FakeCustomerRepository()


class TestHandleMessage:
    def test_조회_성공(self, repo):
        got = handle_message("고객정보#E230096", repo)
        assert got and "미래에셋자산운용" in got

    def test_프리픽스_없이도_동작(self, repo):
        assert handle_message("E230096", repo)

    def test_대상이_아니면_None(self, repo):
        # 대화방 전체 메시지가 유입되므로 무관한 메시지는 반드시 None이어야 한다
        for text in ["점심 뭐 먹지", "", "회의 3시"]:
            assert handle_message(text, repo) is None

    def test_없는_고객번호(self, repo):
        got = handle_message("E999999", repo)
        assert got and "등록되지 않은" in got

    def test_저장소_예외는_사용자에게_노출되지_않는다(self):
        class Broken:
            def fetch(self, code):
                raise RuntimeError("DB 커넥션 실패")

        got = handle_message("E230096", Broken())
        assert got and "오류가 발생" in got
        assert "DB 커넥션" not in got and "RuntimeError" not in got

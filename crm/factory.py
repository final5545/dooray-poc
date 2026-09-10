"""환경변수 → CRM 저장소.

에이전트와 커맨드 서버가 각자 저장소를 만들고 있었다. 실 API가 붙으면서
선택지가 셋이 되어 한 곳으로 모은다 — 두 프로세스가 서로 다른 CRM을 보는
사고를 막는다.

    CRM_KIND=infomax   사내 CRM 실 API (POST, 2026-09-10 연동)
    CRM_KIND=http      GET 방식 (모의 서버 · 일반 REST)
    미설정             CRM_BASE_URL 이 있으면 http, 없으면 메모리 Fake
"""
import os

from .client import FakeCustomerRepository, HttpCustomerRepository
from .infomax import InfomaxCrmRepository


def build_repository(env: dict | None = None):
    """(저장소, 사람이 읽을 설명) 한 쌍을 돌려준다.

    설명은 기동 배너에 찍어 **어느 CRM을 보고 있는지** 눈으로 확인하게 한다.
    실 API와 모의 서버를 헷갈린 채 시연하면 곤란하다.
    """
    env = env if env is not None else os.environ
    base = (env.get("CRM_BASE_URL") or "").strip()
    kind = (env.get("CRM_KIND") or "").strip().lower()
    timeout = float(env.get("CRM_TIMEOUT") or 2.5)

    if not base:
        return FakeCustomerRepository(), "메모리 Fake (1건) — 실 CRM 아님"

    if kind == "infomax":
        path = env.get("CRM_PATH") or "/PCH/LoadCustData"
        return (InfomaxCrmRepository(base, path=path, timeout=timeout),
                f"사내 CRM 실 API {base}{path} (timeout {timeout}s)")

    return (HttpCustomerRepository(
                base,
                url_template=env.get("CRM_URL_TEMPLATE") or "{base}/customers/{code}",
                result_path=env.get("CRM_RESULT_PATH") or "result",
                timeout=timeout),
            f"HTTP GET {base} (timeout {timeout}s) — 모의 서버로 추정")

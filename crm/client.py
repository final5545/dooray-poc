"""CRM API 어댑터.

기획서 §2는 "Dooray! 붓(Bot) ↔ CRM 간 고객정보 단건 조회 API 연동 (Method: GET)"
까지만 정하고 있다. 엔드포인트·인증·응답 필드명이 미확정이므로
**필드 매핑을 코드가 아니라 설정으로** 두었다.
스펙이 확정되면 FIELD_MAP과 URL 템플릿만 고치면 되고 나머지는 그대로다.

응답시간: 기획서 §2 "Timeout 3초 이내 권장".
          메신저 왕복이 0.45초로 측정됐으므로(06 §8) CRM 예산은 약 2.5초.
          예산이 빠듯해 재시도는 하지 않는다 — 한 번 실패하면 사용자에게 알린다.
"""
import logging
from typing import Any, Protocol

import requests

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 2.5

# 내부 표준 키. formatter가 이 이름으로 읽는다.
FIELDS = (
    "code", "customer_type", "name",
    "dept", "manager", "phone_office", "phone_mobile", "email",
    "billing_date", "contract_start", "contract_end", "renewal_start",
    "install_date", "device", "line_type", "line_type2", "carrier",
)

# 내부 표준 키 → CRM 응답 키.
# ⚠️ 아래는 기획서 §4 항목명에서 유추한 **가정**이다. 스펙 확정 시 이 표만 고친다.
#    점 표기로 중첩 경로를 쓸 수 있다 (예: "user.email").
DEFAULT_FIELD_MAP = {
    "code":           "custNo",
    "customer_type":  "custType",
    "name":           "custName",
    "dept":           "deptName",
    "manager":        "userName",
    "phone_office":   "tel1",
    "phone_mobile":   "tel2",
    "email":          "email",
    "billing_date":   "billingDate",
    "contract_start": "contractStartDate",
    "contract_end":   "contractEndDate",
    "renewal_start":  "renewalStartDate",
    "install_date":   "installDate",
    "device":         "deviceType",
    "line_type":      "lineType",
    "line_type2":     "lineType2",
    "carrier":        "carrier",
}


class CustomerRepository(Protocol):
    """조회 대상 저장소. 테스트에서는 Fake로 대체한다."""

    def fetch(self, code: str) -> dict | None:
        """고객번호로 단건 조회. 없으면 None."""
        ...


def dig(data: Any, path: str) -> Any:
    """점 표기 경로로 중첩 값을 꺼낸다. 없으면 None.

    CRM 응답이 평면일지 중첩일지 모르므로 양쪽을 다 받는다.
    """
    cur = data
    for part in (path or "").split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def to_internal(raw: dict, field_map: dict[str, str] | None = None) -> dict:
    """CRM 응답 → 내부 표준 키.

    매핑에 없거나 값이 없는 항목은 넣지 않는다.
    formatter가 '키 없음'과 '값이 빈 문자열'을 똑같이 공란으로 처리하므로 안전하다.
    """
    mapping = field_map or DEFAULT_FIELD_MAP
    out = {}
    for key in FIELDS:
        src = mapping.get(key)
        if not src:
            continue
        value = dig(raw, src)
        if value is not None:
            out[key] = value
    return out


class FakeCustomerRepository:
    """단위테스트·로컬 구동용.

    기본 데이터는 기획서 §5 화면 출력 예시를 그대로 옮긴 것이다
    (전화2·갱신시작일·통신사가 공란인 케이스 포함).
    """

    def __init__(self, rows: dict[str, dict] | None = None):
        self._rows = rows or {
            "E230096": {
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
        }

    def fetch(self, code: str) -> dict | None:
        return self._rows.get(code)


class CrmUnavailable(Exception):
    """CRM 조회 실패 — 미등록이 아니라 시스템 문제.

    '없는 고객번호'(None)와 '조회 자체가 안 됨'을 구분해야
    사용자에게 다른 메시지를 보여줄 수 있다.
    """


class HttpCustomerRepository:
    """사내 CRM API 어댑터.

    스펙 확정 시 고칠 곳은 셋뿐이다 — url_template, field_map, 인증 헤더.
    """

    def __init__(self, base_url: str,
                 url_template: str = "{base}/customers/{code}",
                 field_map: dict[str, str] | None = None,
                 result_path: str = "",
                 headers: dict[str, str] | None = None,
                 timeout: float = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.url_template = url_template
        self.field_map = field_map or DEFAULT_FIELD_MAP
        self.result_path = result_path      # 응답이 래핑돼 있으면 "result" 등
        self.timeout = timeout
        self._session = requests.Session()
        if headers:
            self._session.headers.update(headers)

    def fetch(self, code: str) -> dict | None:
        url = self.url_template.format(base=self.base_url, code=code)
        try:
            r = self._session.get(url, timeout=self.timeout)
        except requests.Timeout as e:
            # 3초 예산이 빠듯해 재시도하지 않는다
            raise CrmUnavailable(f"CRM 응답 지연 ({self.timeout}s 초과)") from e
        except requests.RequestException as e:
            raise CrmUnavailable(f"CRM 연결 실패: {e}") from e

        if r.status_code == 404:
            return None                     # 미등록 고객번호
        if r.status_code >= 400:
            raise CrmUnavailable(f"CRM HTTP {r.status_code}")

        try:
            body = r.json()
        except ValueError as e:
            raise CrmUnavailable("CRM 응답이 JSON이 아님") from e

        raw = dig(body, self.result_path) if self.result_path else body
        if isinstance(raw, list):
            raw = raw[0] if raw else None   # 목록으로 오면 첫 건
        if not isinstance(raw, dict) or not raw:
            return None

        return to_internal(raw, self.field_map)

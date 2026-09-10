"""사내 CRM 어댑터 — 실 API (2026-09-10 연동).

    POST http://{host}/PCH/LoadCustData
         Content-Type: application/json; charset=utf-8
         {"info": [{"UserId": "e120452"}]}

    → {"responseCode": 0, "response": [{...}, ...]}

기존 HttpCustomerRepository(GET, 단건)와 규약이 달라 따로 둔다.
실측(2026-09-10)으로 확인한 동작:

    없는 고객번호   →  200 · responseCode 0 · response []      ← 404가 아니다
    대소문자        →  무관 (e120452 == E120452)
    여러 건         →  info에 여러 개를 넣으면 한 번에 온다
    빈 info         →  ⚠️ responseCode -1 인데 전체 목록이 돌아온다

⚠️ 마지막 항목 때문에 **빈 조회를 절대 보내지 않는다**(§_post). 잘못된 요청에
   고객 목록이 통째로 새어 나오는 동작이라 사내 CRM 담당자에게 보고했다.
"""
import logging
import re

import requests

from .client import CrmUnavailable

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 2.5
DEFAULT_PATH = "/PCH/LoadCustData"

# 응답 키 → 내부 표준 키.
#
# ⚠️ 실 API가 주는 것은 아래가 전부다. 기획서 §4의 [계약정보](청구일·계약시작·
#    계약종료·갱신시작)와 [설치정보] 대부분(설치일자·회선구분·통신사), 그리고
#    이메일이 **응답에 없다**. 포매터가 빈 섹션을 통째로 생략하는 이유다.
FIELD_MAP = {
    "custNo":      "code",
    "accountNm":   "name",
    "addressName": "dept",
    "contactNm":   "manager",
    "telephone":   "phone_office",
    "etc":         "note",
}

# contactType 은 "무료(고객기기)" 처럼 고객구분과 기기가 한 칸에 들어온다.
# 화면에서는 나눠 보여주는 편이 읽기 쉬워 쪼갠다. 괄호가 없으면 통째로 구분에 넣는다.
_TYPE = re.compile(r"^\s*(?P<type>[^(（]+?)\s*[(（](?P<device>[^)）]+)[)）]\s*$")


def split_contact_type(value: str | None) -> tuple[str | None, str | None]:
    """'무료(고객기기)' → ('무료', '고객기기'). 괄호가 없으면 (원문, None)."""
    if not value or not str(value).strip():
        return None, None
    text = str(value).strip()
    m = _TYPE.match(text)
    if not m:
        return text, None
    return m.group("type").strip() or None, m.group("device").strip() or None


def join_address(row: dict) -> str | None:
    """주소와 상세주소를 한 줄로 합친다. 둘 다 없으면 None."""
    parts = [str(row.get(k) or "").strip() for k in ("address", "addressDetail")]
    joined = " ".join(p for p in parts if p)
    return joined or None


def to_internal(row: dict) -> dict:
    """CRM 응답 1건 → 내부 표준 키. 값이 없는 항목은 넣지 않는다."""
    out: dict = {}
    for src, key in FIELD_MAP.items():
        value = row.get(src)
        if value is not None and str(value).strip():
            out[key] = str(value).strip()

    customer_type, device = split_contact_type(row.get("contactType"))
    if customer_type:
        out["customer_type"] = customer_type
    if device:
        out["device"] = device

    address = join_address(row)
    if address:
        out["address"] = address
    return out


class InfomaxCrmRepository:
    """사내 CRM 고객정보 조회.

    단건(fetch)과 배치(fetch_many)를 모두 지원한다. 한 메시지에 고객번호가
    여러 개 들어오는 일이 흔한데, API가 배치를 받으므로 왕복을 아낄 수 있다.
    """

    def __init__(self, base_url: str, path: str = DEFAULT_PATH,
                 timeout: float = DEFAULT_TIMEOUT,
                 headers: dict[str, str] | None = None):
        self.url = base_url.rstrip("/") + path
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {"Content-Type": "application/json; charset=utf-8"})
        if headers:
            self._session.headers.update(headers)

    def _post(self, codes: list[str]) -> list[dict]:
        """고객번호 목록 → 응답 행 목록.

        ⚠️ 빈 목록은 보내지 않는다. 빈 info 를 보내면 CRM이 전체 목록을
           돌려주기 때문이다(실측). 호출자 실수로 정보가 새면 안 된다.
        """
        wanted = [c for c in (codes or []) if c and str(c).strip()]
        if not wanted:
            return []

        payload = {"info": [{"UserId": str(c).strip()} for c in wanted]}
        try:
            r = self._session.post(self.url, json=payload, timeout=self.timeout)
        except requests.Timeout as e:
            # 기획서 §2 예산이 빠듯해 재시도하지 않는다 — 한 번 실패하면 알린다
            raise CrmUnavailable(f"CRM 응답 지연 ({self.timeout}s 초과)") from e
        except requests.RequestException as e:
            raise CrmUnavailable(f"CRM 연결 실패: {e}") from e

        if r.status_code >= 400:
            raise CrmUnavailable(f"CRM HTTP {r.status_code}")
        try:
            body = r.json()
        except ValueError as e:
            raise CrmUnavailable("CRM 응답이 JSON이 아님") from e

        code = body.get("responseCode")
        if code not in (0, "0", None):
            # 조회 실패다. 이때도 response 에 무언가 들어올 수 있으나 쓰지 않는다.
            raise CrmUnavailable(f"CRM responseCode {code}")

        rows = body.get("response")
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []

    def fetch(self, code: str) -> dict | None:
        """고객번호로 단건 조회. 미등록이면 None."""
        rows = self._post([code])
        return to_internal(rows[0]) if rows else None

    def fetch_many(self, codes: list[str]) -> dict[str, dict]:
        """여러 건을 한 번에. {대문자 고객번호: 내부표준}.

        미등록 번호는 결과에 없다. 호출자가 요청 목록과 대조해 판단한다.
        응답이 요청 순서를 지킨다는 보장이 없어 custNo 로 되짚는다.
        """
        out: dict[str, dict] = {}
        for row in self._post(codes):
            data = to_internal(row)
            key = (data.get("code") or "").upper()
            if key:
                out[key] = data
        return out

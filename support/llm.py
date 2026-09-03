"""자유서술 필드 보강 (LLM).

정규식이 잘하는 것과 LLM이 잘하는 것을 나눈다.

  정규식 확정 (LLM이 덮어쓰지 못함)
    - 고객번호  : 형식이 고정(E+5~6자리). LLM에 맡기면 환각 위험만 커진다
    - 희망일    : 패턴이 잡히면 그대로 사용

  LLM 담당
    - 고객사명  : 본문에 자유롭게 적힘("비엔케이자산운용"). CRM 조회 실패 시 폴백
    - 요청유형  : 키워드에 안 걸리는 표현 (정규식 실패 시에만)
    - 세부사항  : 기획서 §5의 '[세부 사항] 엑셀 2016버전'
    - 담당자    : "담당자 : 김수빈 파트너 010-..."

LLM 호출이 실패해도 티켓 생성은 막지 않는다. 보강은 어디까지나 부가값이다.
"""
import json
import logging
from dataclasses import dataclass
from typing import Protocol

import requests

from .extractor import REQUEST_TYPES, SupportRequest

log = logging.getLogger(__name__)

TIMEOUT = 8.0     # 기획서 3초 요건은 CRM 조회 기준. 티켓 등록은 비동기 성격이라 여유를 둔다

_TYPE_LIST = ", ".join(label for label, _ in REQUEST_TYPES)

SYSTEM_PROMPT = f"""너는 사내 기술지원 요청 메시지에서 정보를 추출하는 도구다.
반드시 JSON 객체 하나만 출력한다. 설명이나 코드펜스를 붙이지 마라.

필드:
  customer_name : 고객사(회사) 이름. 없으면 null
  request_type  : 다음 중 하나 또는 null — {_TYPE_LIST}
  detail        : 요청의 핵심을 한 줄로 요약. 없으면 null
  contact       : 요청 담당자 이름과 연락처. 없으면 null

규칙:
- 원문에 없는 정보를 지어내지 마라. 모르면 null.
- 고객번호(E로 시작하는 코드)는 추출하지 마라. 별도로 처리한다.
- customer_name은 회사명만. 부서명이나 사람 이름을 넣지 마라."""


@dataclass
class Enrichment:
    customer_name: str | None = None
    request_type: str | None = None
    detail: str | None = None
    contact: str | None = None


class LLMExtractor(Protocol):
    def enrich(self, text: str, base: SupportRequest) -> Enrichment:
        ...


class NullExtractor:
    """LLM 미설정 시 기본값. 규칙 기반 결과만 쓴다."""

    def enrich(self, text: str, base: SupportRequest) -> Enrichment:
        return Enrichment()


def parse_enrichment(content: str) -> Enrichment:
    """LLM 응답 문자열 → Enrichment. 형식이 어긋나면 빈 값으로 폴백한다."""
    if not content:
        return Enrichment()
    text = content.strip()
    if text.startswith("```"):                       # 코드펜스를 붙이는 모델 대응
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        log.warning("LLM 응답에서 JSON을 찾지 못함")
        return Enrichment()
    try:
        d = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        log.warning("LLM 응답 JSON 파싱 실패")
        return Enrichment()

    def pick(key: str) -> str | None:
        v = d.get(key)
        if v is None:
            return None
        v = str(v).strip()
        return v or None

    rtype = pick("request_type")
    valid = {label for label, _ in REQUEST_TYPES}
    if rtype and rtype not in valid:
        log.warning("LLM이 정의 밖 유형 반환: %r", rtype)
        rtype = None                                  # 분류 체계 밖은 버린다

    return Enrichment(
        customer_name=pick("customer_name"),
        request_type=rtype,
        detail=pick("detail"),
        contact=pick("contact"),
    )


class OpenAICompatExtractor:
    """OpenAI 호환 Chat Completions 엔드포인트.

    사내 vLLM·Ollama·Azure OpenAI·OpenAI 모두 이 인터페이스를 쓴다.
    base_url은 '/chat/completions' 앞까지 넣는다 (예: https://.../v1).
    """

    def __init__(self, base_url: str, model: str,
                 api_key: str = "", timeout: float = TIMEOUT):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.timeout = timeout
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    def enrich(self, text: str, base: SupportRequest) -> Enrichment:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            r = requests.post(self.url, headers=self._headers,
                              json=payload, timeout=self.timeout)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
        except Exception:
            log.exception("LLM 호출 실패 — 규칙 기반 결과만 사용")
            return Enrichment()
        return parse_enrichment(content)

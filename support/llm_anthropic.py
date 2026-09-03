"""Claude(Anthropic) 기반 보강 어댑터.

Anthropic API는 OpenAI 호환이 아니라 공식 SDK를 쓴다(llm.py의 OpenAICompatExtractor로는 붙지 않는다).

모델: Claude Haiku 4.5 (claude-haiku-4-5)
  짧은 한국어 메시지 → 필드 4개 JSON 추출. 추론이 필요 없는 분류·추출 작업이라
  상위 모델의 thinking 지연이 순수 손해다. Haiku는 thinking 계열이 없어 빠르다.
  비용도 1,000건당 약 $1 수준.

구조화 출력(output_config.format)으로 JSON 스키마를 강제하므로
모델이 코드펜스나 설명문을 붙일 수 없다. 그래도 parse_enrichment()를 거쳐
요청유형 enum 검증과 폴백을 한 번 더 태운다.
"""
import logging

import anthropic

from .extractor import SupportRequest
from .llm import SYSTEM_PROMPT, Enrichment, parse_enrichment

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 512      # 필드 4개 JSON. 넉넉하게 잡아도 이 정도면 충분하다
TIMEOUT = 8.0

# 모든 필드를 required로 두고 null을 허용한다.
# 선택 필드로 두면 모델이 키 자체를 빠뜨려 파싱 분기가 늘어난다.
OUTPUT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "customer_name": {"type": ["string", "null"]},
            "request_type": {"type": ["string", "null"]},
            "detail": {"type": ["string", "null"]},
            "contact": {"type": ["string", "null"]},
        },
        "required": ["customer_name", "request_type", "detail", "contact"],
        "additionalProperties": False,
    },
}


class AnthropicExtractor:
    """Claude로 자유서술 필드를 보강한다."""

    def __init__(self, api_key: str = "", model: str = DEFAULT_MODEL,
                 timeout: float = TIMEOUT):
        # api_key가 비면 SDK가 환경변수·프로필에서 자격증명을 찾는다
        self._client = (anthropic.Anthropic(api_key=api_key, timeout=timeout)
                        if api_key else anthropic.Anthropic(timeout=timeout))
        self.model = model
        self._disabled = False      # 인증 실패 시 차단 (회로 차단기)
        self.last_usage: tuple[int, int] | None = None   # (입력, 출력) 토큰

    def enrich(self, text: str, base: SupportRequest) -> Enrichment:
        if self._disabled:
            return Enrichment()

        try:
            res = self._client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": text}],
                output_config={"format": OUTPUT_SCHEMA},
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            # 재시도해도 낫지 않는다. 매 메시지마다 두드리지 않도록 이 세션에서는 끈다.
            self._disabled = True
            log.error("Claude 인증 실패 — LLM 보강을 끕니다 (키 확인 필요): %s", e)
            return Enrichment()
        except anthropic.NotFoundError as e:
            self._disabled = True
            log.error("Claude 모델을 찾을 수 없음 — LLM 보강을 끕니다: %s", e)
            return Enrichment()
        except anthropic.APIStatusError as e:
            # 429·5xx 등 일시적 오류는 다음 메시지에서 다시 시도한다
            log.warning("Claude 호출 실패(%s) — 규칙 기반 결과만 사용", e.status_code)
            return Enrichment()
        except Exception:
            log.warning("Claude 호출 실패 — 규칙 기반 결과만 사용", exc_info=False)
            return Enrichment()

        u = res.usage
        log.debug("Claude usage: in=%s out=%s", u.input_tokens, u.output_tokens)
        self.last_usage = (u.input_tokens, u.output_tokens)
        content = next((b.text for b in res.content if b.type == "text"), "")
        return parse_enrichment(content)

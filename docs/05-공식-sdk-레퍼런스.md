# Dooray! SDK 공식 레퍼런스 (Python)

> 출처: Dooray helpdesk "Dooray! SDK 가이드"
> **익스텐션 에이전트 + SDK를 쓸 경우의 공식 기준.**
> 패키지 실측과의 차이는 `02-sdk-분석에서-알아낸-것.md` 참조.
>
> ⚠️ **현행 PoC는 SDK를 쓰지 않는다.** 자체 구현으로 전환했으므로
> 코드 작성 1순위는 `06-자체구현-레퍼런스.md`다. 이 문서는 개념 참조용.

---

## 🔴 가장 중요한 차이 — 공식 문서에 메신저만 있음

공식 SDK 가이드에 문서화된 범위:
- 이벤트 타입: **`message`, `all`**
- 서비스: **`messenger`**
- 서비스 네임스페이스: **`agent.messenger`** (`send_message`, `reply_to_message`)

**패키지 실물에는 Task API 13종, Wiki API 16종이 존재하지만 공식 문서에 없음.**
`Agent.__init__`의 `services` 파라미터도 공식 문서에는 없음.

→ **미문서화 API. 지원·안정성 보장 없음.**
→ 기술지원 현황판 기획이 Task API에 의존하는데, 이 부분은 Dooray 확인이 필요함.

---

## 1. 설치

공식 가이드는 **압축 파일(.zip/.tar.gz) 배포** 기준으로 서술
(단, 실제로는 PyPI에도 공개되어 있음 — `pip install --pre dooray-sdk`).

```bash
unzip python-dooray-sdk.zip      # 또는 tar -xzf python-dooray-sdk.tar.gz
cd python-dooray-sdk

python3 -m venv .venv && source .venv/bin/activate

pip install -r requirements.txt
# 또는
pip install -e ".[aiohttp]"      # async 포함 권장
pip install -e ".[all]"          # LLM 포함
```

### 오프라인 설치 (폐쇄망 대비)

```bash
# 온라인 환경
pip download -r requirements.txt -d ./packages/

# 오프라인 환경
pip install --no-index --find-links=./packages/ -r requirements.txt
```

> 향후 서버망이 폐쇄망일 경우 이 방식 사용.

### 의존성

| 구분 | 패키지 | 버전 | 설명 |
|---|---|---|---|
| 필수 | `requests` | >= 2.25.0 | 동기 HTTP |
| 필수 | `websocket-client` | >= 1.0.0 | 동기 WebSocket |
| 필수 | `python-dotenv` | >= 1.0.0 | .env 로딩 |
| 권장(async) | `aiohttp` | >= 3.8.0 | 비동기 HTTP/WebSocket |
| 선택 | `websockets` | >= 10.0 | 대체 WebSocket 구현 |
| LLM | `langchain-core` | >= 0.3.0 | LLM 연동 |
| LLM | `langchain-openai` | >= 0.3.0 | OpenAI 계열 |
| LLM | `pydantic` | >= 2.0.0 | LLM 설정 검증 |
| 템플릿 | `cookiecutter` | >= 2.0.0 | 스캐폴딩 |

extras: `[aiohttp]`, `[websockets]`, `[templates]`, `[llm]`, `[all]`

### 환경변수

| 변수 | 필수 | 설명 | 예시 |
|---|---|---|---|
| `DOORAY_AGENT_TOKEN` | 예 | 에이전트 인증 토큰 | |
| `DOORAY_DOMAIN` | 예 | Dooray 도메인 (**프로토콜 제외**) | `infomax.dooray.com` |

---

## 2. Agent 클래스

```python
class Agent:
    def __init__(
        self,
        token: str = None,                 # 없으면 DOORAY_AGENT_TOKEN
        domain: str = None,                # 없으면 DOORAY_DOMAIN
        ignore_self: bool = True,          # 에이전트 자신의 메시지 무시
        auto_reconnect_enabled: bool = True,
        **kwargs                           # SocketModeClient reconnect_* 등
    )
```

> 토큰/도메인 검증은 `__init__` 시점에 수행. 누락·형식 오류 시 `DoorayConfigurationError`.

### 속성
`token`, `domain`, `base_url`, `is_connected`, `messenger`(ServiceNamespace)

### 메서드

| 메서드 | 설명 |
|---|---|
| `run()` | 실행 (블로킹) |
| `start()` | 비동기 시작 (`await agent.start()`) |
| `connect()` | 연결만 수행 |
| `disconnect()` | 연결 종료 |
| `on(event_type="all", action=None, service=None)` | 이벤트 핸들러 데코레이터 |
| `add_handler(event_type, handler, action=None, service=None)` | 비데코레이터 등록 |
| `reply_to(trigger, response)` | 단순 텍스트 응답 매핑 |
| `on_disconnect(func)` / `on_reconnect(func)` | 연결 콜백 |
| `messenger.send_message(channel, text)` | 메시지 전송 |

---

## 3. 이벤트 핸들러

```python
@agent.on(event_type="all", action=None, service=None)
```

| 매개변수 | 값 | 설명 |
|---|---|---|
| `event_type` | `message`, `all` | 이벤트 타입 필터 |
| `action` | `create`, `update`, `delete` 등 | 액션 필터 |
| `service` | `messenger` | 서비스 필터 |

### 핸들러 시그니처 (자동 감지)

| 시그니처 | 설명 |
|---|---|
| `(req)` | 요청 객체만 |
| `(req, client)` | **권장** — `client.messenger.*` 사용 가능 |
| `(data)` / `(payload)` | `req.data` dict만 |

동기·비동기 모두 지원.

### 기본 예제 (공식)

```python
from dooray_sdk import Agent

agent = Agent()

@agent.on("message")
async def handle_message(req, client):
    if req.text:
        await client.messenger.send_message(
            channel=req.channel_info.id,
            text=f"받은 메시지: {req.text}",
        )

agent.run()
```

### 재연결 훅

```python
@agent.on_disconnect
def report_drop(client, info):
    # info: attempt / error / close_code / close_reason
    print(f"disconnected: {info['close_code']}")

@agent.on_reconnect
async def announce(client, info):
    # info: attempt / delay / error / close_code / close_reason
    print(f"reconnect #{info['attempt']} in {info['delay']:.1f}s")
```

---

## 4. 메신저 API (`agent.messenger` / `client.messenger`)

| 메서드 | 설명 |
|---|---|
| `send_message(channel, text, **kwargs)` | 채널에 새 메시지 |
| `reply_to_message(channel, message_id, text, **kwargs)` | 특정 메시지에 인용 답장 |

```python
@agent.on("message")
async def handle(req, client):
    channel = req.channel_info.id

    await client.messenger.send_message(channel=channel, text="pong")

    await client.messenger.reply_to_message(
        channel=channel,
        message_id=req.entity.data.id,     # ← 메시지 ID 경로
        text="인용 답장입니다.",
    )
```

> **공식 문서에 `reply_in_thread` 없음.** 패키지에는 시그니처만 있고 `NotImplementedError`.
> 스레드 답장은 현재 미지원으로 간주할 것.
>
> **메시지 수정 API도 없음.** 필요 시 `WebClient.put()`으로 REST 직접 호출.

---

## 5. 요청 객체 `SocketModeRequest`

```python
@dataclass
class SocketModeRequest:
    envelope_id: str
    type: str
    payload: Dict[str, Any]
    accepts_response_payload: bool = False
    service: str = "messenger"
    action: str = ""
    entity: EntityWrapper = None
    actor: ActorWrapper = None
    action_data: Optional[Dict[str, Any]] = None
    channel_data: Optional[Dict[str, Any]] = None
```

### 구조

```
SocketModeRequest
├── entity: EntityWrapper      # 엔티티 정보
│   ├── type: str              # "message"
│   └── data: MessageData
├── actor: ActorWrapper        # 액션 수행자
│   ├── type: str
│   ├── data: DataWrapper
│   └── organizationMember: LazyMemberData
└── action: ActionWrapper
    ├── type: str
    └── data: DataWrapper
```

### 편의 속성 / 메서드

`is_message`, `text`, `channel_info`(id/scope/type), `data`
`is_service()`, `is_action_type()`, `get_message_text()`, `get_channel()`, `to_dict()`, `from_dict()`

### MessageData (`req.entity.data`)

| 속성 | 타입 | 설명 |
|---|---|---|
| `id` | str | **메시지 ID** (인용 답장에 사용) |
| `channelId` | str | 채널 ID |
| `senderId` | str | 보낸 사람 멤버 ID |
| `text` | str | 메시지 텍스트 |
| `sentAt` | int | timestamp ms |
| `seq` | int | 시퀀스 번호 |
| `directMemberId` | str | DM 상대방 멤버 ID |
| `parentChannelId` | str | **부모 채널 ID (스레드)** |
| `type` | int | 0: 일반, 1: 시스템 |

> ~~**파일 첨부 필드 없음** → 메신저 파일 수신 불가로 보임.~~
> 🔴 **2026-09-02 실측에서 뒤집힘.** WebSocket 프레임에는 `content.file` 객체가
> 실제로 존재하며 `fileName`·`fileSize`·`mimeType`을 전부 받는다.
> SDK의 `MessageData`가 모델링하지 않았을 뿐이다. → `06-자체구현-레퍼런스.md` §4
>
> `type` 필드로 시스템 메시지 필터링 가능 (봇 초대/퇴장 등 노이즈 제거).
> 실측값: `0`=일반 / `1`=시스템 / `4`=파일 / `10`=답글.

### ActorWrapper

`type`(예: `organizationMember`), `id`, `data`, `organizationMember`

**LazyMemberData 필드**
`id`, `name`, `externalEmailAddress`, `nickname`, `englishName`, `nativeName`,
`userCode`, `locale`, `timezoneName`, `idProviderType`(sso/service),
`idProviderUserId`, `defaultOrganization`, `displayMemberId`

**Lazy Loading**: WebSocket 메시지에 포함된 로컬 데이터는 즉시 반환,
없는 필드는 API 호출. **조회 결과 10분 캐시.**

```python
@agent.on("message")
async def handle(req, client):
    member = req.actor.organizationMember

    member_id = member.id                        # 로컬 — API 호출 없음
    name = await member.name                     # API 호출 발생
    email = await member.externalEmailAddress
    full_data = await member                     # 전체 조회
```

> ⚠️ **async 핸들러 안에서 로컬에 없는 필드는 반드시 `await`.**
> `userCode`가 사번 매핑 키로 쓰일 가능성 있음 — 실측 확인.

### DataWrapper

점 표기법 + dict 인터페이스 모두 지원.
```python
data.id            data["id"]         data.get("text", "기본값")
"id" in data       len(data)          data.keys() / values() / items()
```

---

## 6. Web 클라이언트

```python
class WebClient:
    def __init__(self, token, base_url="https://api.dooray.com",
                 timeout: int = 30, user_agent_prefix=None, user_agent_suffix=None, **kwargs)
```

| 메서드 | 설명 |
|---|---|
| `messenger` | MessengerAPI 네임스페이스 |
| `get_member(member_id)` | 조직 멤버 정보 조회 |
| `get(endpoint, params=None)` | GET |
| `post(endpoint, data=None)` | POST |
| **`put(endpoint, data=None)`** | **PUT** ← 메시지 수정 우회에 사용 |
| `delete(endpoint)` | DELETE |
| `fetch_socket_mode_token()` | Socket Mode 토큰 발급 |

`AsyncWebClient`는 동일 시그니처의 async 버전. **기본 timeout 30초.**

> `get/post/put/delete` 범용 메서드가 있으므로, SDK가 감싸지 않은 REST API도
> 별도 HTTP 클라이언트 없이 호출 가능. **"처리 중 → 결과 갱신" 우회 경로.**

---

## 7. LLM 연동

```python
async def query(*, prompt, options: QueryOptions | None = None) -> AsyncIterator[Message]
```

### 🔴 `options`와 `options.langchain_config`는 **필수**

누락 시 `DoorayLLMConfigurationError`.
→ 가이드 위키의 `query(prompt=prompt)` 단독 호출 예제는 **동작하지 않음.**

```python
@dataclass
class QueryOptions:
    langchain_config: BaseLLMConfig | None = None   # 필수
    system_prompt: str | None = None
    temperature: float | None = None                 # 0.0 ~ 2.0
    max_tokens: int | None = None
    tools: list[dict] | None = None                  # function calling
    tool_choice: str | dict | None = None            # auto/none/required/특정 도구
    stream: bool = True
```

### 지원 프로바이더 (3종)

`from dooray_sdk.llm.langchain import ...`

| 설정 클래스 | 주요 인자 | 비고 |
|---|---|---|
| `DoorayAIConfig` | `token: SecretStr`, `domain`, `model` | base_url은 domain에서 자동 유도 |
| `OpenAIConfig` | `api_key: SecretStr`, `model`, `base_url?` | |
| `AzureOpenAIConfig` | `azure_endpoint`, `model`, `api_key: SecretStr` | |

> **Claude / Gemini 전용 config 없음.** 위키 가이드의 "Claude 등 지원" 서술과 불일치.
> 다만 `OpenAIConfig`에 `base_url` 인자가 있어 OpenAI 호환 엔드포인트는 우회 가능.
> 또는 `query()`를 쓰지 않고 직접 호출.

> **`DoorayAIConfig`가 에이전트 토큰을 그대로 사용** → 별도 LLM 계약 없이
> Dooray AI로 PoC 가능. 단 AI 구독 범위 확인 필요.

### 예제

```python
from dooray_sdk import query, QueryOptions
from dooray_sdk.llm.langchain import OpenAIConfig
from pydantic import SecretStr

options = QueryOptions(
    langchain_config=OpenAIConfig(api_key=SecretStr("your-key"), model="gpt-4o-mini")
)

answer = ""
async for message in query(prompt="Hello!", options=options):
    answer += message.text or ""
```

### 응답 타입

```python
@dataclass
class Message:
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    @property
    def text(self) -> str | None: ...       # content 별칭
    @property
    def has_tool_calls(self) -> bool: ...

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str                          # JSON 문자열
    def parse_arguments(self) -> dict: ...
```

### 🟢 Function Calling 지원

```python
tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get weather for a location",
        "parameters": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
        },
    },
}]

options = QueryOptions(langchain_config=..., tools=tools)

async for message in query(prompt="서울 날씨 알려줘", options=options):
    if message.has_tool_calls:
        for tc in message.tool_calls:
            print(f"Call: {tc.name}({tc.parse_arguments()})")
    else:
        print(message.text, end="")
```

> **CRM 조회 시나리오에 직접 활용 가능.**
> 자연어 → 고객번호 추출을 프롬프트 문자열 파싱 대신 function calling으로 구조화하면
> 훨씬 안정적. (단순 E-code 추출은 정규식이 더 저렴하고 빠름 — 복합 질의에서만 유용)

---

## 8. 오류 처리

```
DooraySDKError (Exception)
├─ DoorayConfigurationError      토큰/도메인 미설정·형식 오류
├─ DoorayConnectionError         연결 실패
│  └─ DoorayWebSocketError       WebSocket 오류
├─ DoorayAuthenticationError     인증 실패
│  └─ DoorayTokenError           토큰 오류
├─ DoorayRequestError            HTTP 실패 (status_code / response_body 포함)
├─ DoorayTimeoutError            타임아웃
└─ DoorayLLMError
   ├─ DoorayLLMConfigurationError   langchain_config 누락/오류, langchain 미설치
   └─ DoorayLLMRequestError         LLM API 요청 실패
```

각 예외는 `error_code` 와 `context` 를 포함할 수 있음.

```python
from dooray_sdk import Agent, DoorayConfigurationError

try:
    agent = Agent()
except DoorayConfigurationError as e:
    print(f"설정 오류: {e}")      # 예: [MISSING_TOKEN] ...
    exit(1)

@agent.on("message")
async def handle(req, client):
    try:
        ...
    except Exception as e:
        logger.exception("처리 오류")   # 사용자에게 에러 노출 금지
```

---

## 9. 공식 export 목록

```python
from dooray_sdk import (
    Agent,
    WebClient, AsyncWebClient,
    MessengerAPI, AsyncMessengerAPI,
    SocketModeClient, SocketModeRequest, SocketModeResponse,
    query, QueryOptions, Message, ToolCall,
    DooraySDKError, DoorayConfigurationError, DoorayConnectionError,
    DoorayWebSocketError, DoorayAuthenticationError, DoorayTokenError,
    DoorayRequestError, DoorayTimeoutError,
    DoorayLLMError, DoorayLLMConfigurationError, DoorayLLMRequestError,
)
```

> `AsyncTaskAPI` / `TaskAPI` / `AsyncWikiAPI` / `WikiAPI` 는 **패키지에는 존재하나
> 공식 export 목록에 없음.** 미문서화 API.

---

## 10. 자동 응답 매핑 (간단 기능)

```python
agent.reply_to("ping", "pong")
agent.reply_to("hello", "안녕하세요!")
```

연결 확인용 스모크 테스트에 유용.

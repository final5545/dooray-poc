# python-dooray-sdk 분석에서 알아낸 것

> 대상: `dooray-sdk 0.1.0b1` (PyPI, MIT)
> 분석일: 2026-09-02
> 이 문서는 **패키지 소스를 직접 읽어 얻은 것**만 다룬다.
> 실제 Dooray 서버 동작을 실측한 결과는 `06-자체구현-레퍼런스.md`.

---

## 0. 요약 — 왜 이 분석이 결정적이었나

PoC는 **AI 프리미엄 라이선스**라는 블로커에 막혀 있었다.
익스텐션 에이전트를 만들 수 없으니 토큰이 없고, 토큰이 없으니 아무것도 못 한다는 상태였다.

그런데 SDK 소스를 읽어보니 **Socket Mode 인증이 에이전트 전용이 아니었다.**
이미 발급 가능한 개인 액세스 토큰으로 같은 엔드포인트를 호출할 수 있었고,
실제로 연결에 성공했다.

**라이선스 없이 PoC 전 구간을 진행할 수 있게 된 것이 이 분석의 성과다.**

패키지를 설치만 해보고 넘어갔다면 얻지 못했을 결론이다.
공식 문서에는 이 경로가 전혀 서술되어 있지 않다.

---

## 1. 패키지 기본 정보

| 항목 | 값 |
|---|---|
| 패키지명 | `dooray-sdk` |
| 버전 | `0.1.0b1` (**베타**) |
| 라이선스 | MIT |
| Python | 3.8+ (실사용 3.11+ 권장) |
| 배포 | PyPI 공개 (`--pre` 필요) |

```bash
pip install --pre "dooray-sdk[templates,llm]"
```

> 공식 가이드는 zip/tar.gz 배포만 서술하지만 실제로는 PyPI에 공개되어 있다.
> 폐쇄망 배포 시 `pip download` → `--no-index` 방식 사용.

---

## 2. 🔴 인증 체인 — 가장 큰 수확

`web/token.py`, `web/client.py`, `socket_mode/client.py`를 읽어 복원한 흐름.

```
① POST https://api.dooray.com/common/v1/socket-mode/tokens
   Authorization: dooray-api {토큰}
   → result: { accessToken(JWT), tenantId, organizationMemberId }

② wss://{도메인}/messenger/v5/ws/{tenantId}/{organizationMemberId}
   Authorization: Bearer {accessToken}
```

### 여기서 눈에 띈 것 넷

**1. 인증 헤더가 `dooray-api {token}`** (`web/client.py:63`)
Dooray 공개 REST API의 **개인 액세스 토큰과 완전히 동일한 스킴**이다.
에이전트 전용 형식이 아니다.

**2. 토큰 교환 경로가 `/common/v1/...`**
`/agent/...` 같은 전용 네임스페이스가 아니라 공용 경로다.

**3. 응답 필드가 `organizationMemberId`**
에이전트 ID가 아니라 **조직 멤버 ID**를 돌려준다.

**4. WebSocket 경로가 `/messenger/v5/ws/{tenantId}/{memberId}`**
에이전트가 아니라 멤버 단위로 소켓이 열린다.

→ **이 소켓은 "에이전트의 소켓"이 아니라 "조직 멤버의 메신저 소켓"이다.**
   익스텐션 에이전트도 조직 멤버 하나로 취급될 뿐이다.
   그래서 개인 액세스 토큰으로도 열린다.

### API base URL 유도 규칙 (`_domain.py`)

도메인의 첫 서브도메인을 떼고 `api.`를 붙인다.

```
infomax.dooray.com     → https://api.dooray.com
nhnent.dev.dooray.com  → https://api.dev.dooray.com
company.dooray.co.kr   → https://api.dooray.co.kr
```

---

## 3. WebSocket 프레임 프로토콜

`socket_mode/client.py:_on_message`가 하는 일을 그대로 읽으면 프로토콜이 나온다.

| `type` | 처리 |
|---|---|
| `sessionInfo` | 연결 수립 알림. SDK는 로깅만 하고 **버린다** |
| `channelLog` + `action ∈ {create, update}` | 사용자 핸들러로 전달 |
| 그 외 | **전부 폐기** |

추가 필터:
- `content.type == 1`(시스템 메시지)이면 폐기
- `content`에 `channelId`가 없으면 루트에서 가져와 채움
- `actor`가 없으면 `content.senderId`로 대체 구성

keepalive는 `{"type":"ping"}`을 주기 전송하고 `pong`을 받는다.

> **SDK가 버리는 것들이 우리에겐 필요했다.**
> `channelLog delete`(삭제), `reaction`(이모지 반응), 그리고 나중에 확인된
> 봇 알림(`content.type == 2`)이 전부 SDK 필터에 걸려 사라진다.
> 자체 구현이 SDK보다 많은 정보를 얻는 이유다.

---

## 4. 서비스 레지스트리 — 문서에 없는 확장 지점

`socket_mode/registry.py`

```python
SERVICE_REGISTRY = {
    "messenger/channelLog": ServiceMapping(service="messenger", type="message"),
    "task/task":            ServiceMapping(service="task",      type="task"),
    "wiki/page":            ServiceMapping(service="wiki",      type="page"),
}
SUPPORTED_SERVICES = ["messenger", "task", "wiki"]
SUPPORTED_ACTIONS  = ["create", "update", "delete", "comment"]
```

업무·위키 이벤트 매핑이 준비되어 있다.

> ⚠️ 다만 **실측 결과 업무 이벤트는 이 소켓으로 오지 않는다**(0건).
> WebSocket 경로가 `/messenger/v5/ws/`인 것과 일관된다.
> 레지스트리는 향후 확장을 위한 자리로 보인다. `06` §4 참조.

---

## 5. 공식 문서와 패키지의 차이

| 항목 | 공식 문서 | 패키지 실물 | 판단 |
|---|---|---|---|
| Task API (13종) | **없음** | 존재 | 미문서화 |
| Wiki API (16종) | **없음** | 존재 | 미문서화 |
| `Agent(services=[...])` | **없음** | 존재 | 미문서화 |
| `@agent.on("task")` / `("page")` | **없음** | 존재 | 미문서화 |
| `reply_in_thread` | 없음 | 시그니처만, `NotImplementedError` | 미지원 |
| `req.reply()` | 없음 | 존재하나 deprecated | 사용 금지 |
| `@agent.messenger` (데코레이터) | 없음 | 존재하나 deprecated | 사용 금지 |
| active/standby HA | 없음 | README에 명시 | 동작함 |

### 미문서화 API 목록 (참고용)

**Task (13)**
```
create_task  get_task  get_task_by_id  list_tasks  modify_task
set_workflow  set_assignee_workflow  set_done
create_comment  list_comments  get_comment  modify_comment  delete_comment
```

**Wiki (16)**
```
list_wikis  create_page  list_pages  get_page  get_page_by_id  modify_page
set_page_title  set_page_content  set_page_referrers  move_page  delete_page
create_comment  list_comments  get_comment  modify_comment  delete_comment
```

동기/비동기 짝 모두 제공. **SDK export 목록에는 없다.**

> 이 API들이 가리키는 REST 엔드포인트는 **실측에서 정상 동작을 확인했다**(`06` §6).
> SDK 표면이 미문서화일 뿐 서버 기능 자체는 살아 있다.

---

## 6. 함정 넷 — 소스를 안 읽으면 못 잡는 것

### 6.1 `sslopt`를 넘기지 않는다

`socket_mode/client.py:248`

```python
self.ws.run_forever(ping_interval=..., ping_timeout=...)   # sslopt 없음
```

`websocket-client`는 시스템 기본 CA 스토어를 쓰는데 macOS Python에서는 불완전해
`CERTIFICATE_VERIFY_FAILED`가 난다.

→ **정식 에이전트 토큰이 있었어도 이 환경에서는 SDK가 그대로 실패했을 것이다.**
   자체 구현에서는 `sslopt={"ca_certs": certifi.where()}`를 넘긴다.

### 6.2 재연결은 끊긴 뒤에 토큰을 재발급한다

`socket_mode/client.py:_handle_reconnect`

```python
time.sleep(delay)
self._fetch_socket_mode_token()      # 끊긴 다음에야 갱신
```

소켓 토큰(JWT) 수명이 1시간이므로 **1시간마다 짧은 단절이 생긴다.**
자체 구현은 만료 120초 전에 스스로 끊고 재발급해 무중단으로 처리한다.

재연결 파라미터: `reconnect_delay=1`초 시작, 지수 백오프, 상한 `max_reconnect_delay=60`초, 무한 재시도.

### 6.3 토큰당 활성 연결 1개

README에만 있는 내용.

- 서버가 토큰당 active WebSocket 1개만 허용
- 중복 접속 시 close code **`1008 AGENT_ALREADY_CONNECTED`**
- SDK는 중복 프로세스를 STANDBY로 두고 15초마다 재시도
- active 종료 시 standby 자동 승격

> **실측 확인**: 개인 액세스 토큰에도 동일하게 적용된다.
> 개발 PC와 서버에서 같은 토큰을 쓰면 한쪽이 **조용히** 밀린다.
> 환경별로 토큰을 분리할 것(개인 토큰은 계정당 10개).

### 6.4 `req.reply()`는 경고를 발생시키지 않는다

소스에서 `SocketModeRequest.reply()`는 `DeprecationWarning`을 직접 띄우지 않는다.
"사용자 핸들러에서만 경고가 나도록" 설계되어 있어 코드만 보면 정상 API로 오인하기 쉽다.

**README의 "Summary of deprecated surfaces" 표가 기준이다.**

잔여 호출부 탐지:
```bash
python -W error::DeprecationWarning main.py
```

---

## 7. Deprecated 표면 총정리

> README 명시: **다음 마이너 릴리스에서 제거 예정.**

| 구형 | 신형 |
|---|---|
| `req.reply(text)` | `await client.messenger.send_message(channel=req.channel_info.id, text=...)` |
| `@agent.messenger` / `@agent.task` / `@agent.wiki` (데코레이터) | `@agent.on("message")` / `@agent.on(service="messenger")` |
| `Agent.send_message` / `get_channels` / `get_messages` / `get_user_info` | `agent.messenger.<method>(...)` |
| `WebClient` / `AsyncWebClient` 의 `.send_message` 등 | `client.messenger.<method>(...)` |
| `req.channel` (property) | `req.channel_info.id` |

> 헷갈리는 지점: `agent.messenger`는 **속성 접근**으로는 정상 API
> (`agent.messenger.send_message`), **데코레이터 호출**로 쓸 때만 deprecated.

---

## 8. 메신저 API 제약

| 목적 | 메서드 | 상태 |
|---|---|---|
| 새 메시지 | `send_message(channel, text, **kwargs)` | ✅ |
| 인용 답장 | `reply_to_message(channel, message_id, text, **kwargs)` | ✅ |
| 스레드 답장 | `reply_in_thread(parent_channel_id, text)` | ❌ `NotImplementedError` |
| **메시지 수정** | — | ❌ 메서드 자체가 없음 |

`reply_in_thread` 소스 주석: *"ADR-007, 1차에서는 미구현. 외부 표면 안정성을 위해 시그니처는 미리 노출."*

REST 경로는 소스에서 그대로 읽을 수 있다(`web/messenger.py`):
```
POST /messenger/v1/channels/{channel}/logs
POST /messenger/v1/channels/{channel}/logs/{messageId}/reply
```

`WebClient`에 `get/post/put/delete` 범용 메서드가 있어 SDK가 감싸지 않은 REST도
별도 HTTP 클라이언트 없이 호출 가능하다.

---

## 9. LLM 프로바이더 — 문서와 불일치

구현된 config 클래스는 **3종뿐**:
`OpenAIConfig` / `AzureOpenAIConfig` / `DoorayAIConfig`

factory 분기: `openai` / `azure_openai` / `dooray_ai` — 그 외 `Unknown provider type` 에러.

> `QueryOptions` 주석에 VertexClaude·VertexGemini 언급이 있으나 **클래스 미구현.**
> 위키 가이드의 "OpenAI, Azure OpenAI, Claude 등 지원" 서술은 사실과 다르다.

또한 `query()`는 `options.langchain_config`가 **필수**다.
누락 시 `DoorayLLMConfigurationError`. 위키 가이드의 `query(prompt=...)` 단독 호출 예제는 동작하지 않는다.

---

## 10. CLI

```bash
dooray-sdk list                 # 템플릿 목록
dooray-sdk init echo-agent      # cookiecutter 스캐폴딩
dooray-sdk version
```

> ⚠️ 생성되는 `main.py`가 **구형 API**(`@agent.messenger` + `req.reply`)를 쓴다.
> 그대로 쓰면 안 된다.

---

## 11. SDK를 쓰지 않기로 한 이유

분석 결과 SDK 없이 직접 구현하는 편이 낫다고 판단했다.

| 이유 | 내용 |
|---|---|
| **라이선스 우회의 전제** | 개인 토큰 방식은 SDK가 상정한 사용법이 아니다 |
| **프레임 손실** | SDK가 `delete`·`reaction`·봇알림(`type=2`)을 전부 버린다 |
| **sslopt 버그** | 우리 환경에서 SDK는 연결조차 안 된다 (§6.1) |
| **토큰 갱신 방식** | 끊긴 뒤 재발급 → 1시간마다 단절 (§6.2) |
| **베타 + 미문서화 의존** | 필요한 기능 상당수가 export 목록 밖 |
| **의존성** | 자체 구현은 `requests` + `websocket-client` + `certifi` 셋이면 된다 |

**SDK는 "명세서"로서 결정적이었고, "런타임"으로는 쓰지 않는다.**

---

## 12. 그래도 계속 참조할 것

SDK를 런타임에서 걷어냈어도 아래는 계속 소스를 보고 확인한다.

- **REST 엔드포인트 경로** — `web/messenger.py`, `web/task.py`, `web/wiki.py`에
  공식 문서에 없는 경로들이 그대로 적혀 있다
- **재연결 정책 수치** — 백오프 상한, ping 간격
- **에러 계층** — `DooraySDKError` 이하 분류가 REST 응답 코드 해석에 유용
- **버전 업 시 변경 추적** — 새 릴리스가 나오면 프로토콜 변경 여부를 여기서 먼저 본다

폐기하지 말고 `.venv`에 남겨둘 것.

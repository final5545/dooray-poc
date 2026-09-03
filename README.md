# Dooray 기술지원 자동화 PoC

두레이 대화방에서 고객정보를 조회하고, 기술지원 요청을 업무로 등록하고,
버튼으로 처리 상태를 바꿉니다. **AI 프리미엄 라이선스 없이** 개인 액세스 토큰과
사내 서버만으로 만들었습니다.

연합인포맥스 AI부 · 2026.09

---

## 무엇을 하나

| | 어디서 | 무엇을 |
|---|---|---|
| **고객정보 조회** | `CRM 조회` 방 | 고객번호를 섞어 쓰면 고객 카드가 온다 |
| **요청 접수** | `CRM 조회` 방 | 요청서 양식 11종 → 확인 → 업무 등록 |
| **자유 서술 접수** | `기술 지원 현황판` 방 | 양식 없이 쓴 요청을 Claude가 읽고 등록 |
| **처리** | 양쪽 | `/처리` → `[수락] [완료]` 버튼 · 되돌리기 |
| **완료 통보** | 양쪽 | 방에 봇 공지 + 요청자 개인 알림 |

---

## 구성

```
정원석 맥                          ai-node-1 (Docker Swarm)
├── standalone/agent.py            ├── dooray_command
│   두레이 소켓 수신 (아웃바운드)  │   /처리 · /접수 · 버튼 (인바운드)
│   고객 조회 · 요청 접수          │   https://dooray.infomaxai.com
│   완료 감지 폴링 300초           │
└── standalone/mock_crm.py :8900   └── mockcrm :8900
```

**방향이 반대라 프로세스가 둘입니다.** 메시지 수신은 우리가 두레이에 붙고
(소켓), 버튼 클릭은 두레이가 우리를 호출합니다(HTTPS).

---

## 띄우기

### 맥 — 에이전트

```bash
cp .env.example .env        # 토큰과 채널 ID 채우기
pip install requests websocket-client certifi python-dotenv

python standalone/mock_crm.py 8900 &
python standalone/agent.py
```

### 서버 — 커맨드

```bash
docker build -f deploy/Dockerfile -t dooray-command:latest .
set -a && source .env && set +a
docker stack deploy -c deploy/docker-compose.yml dooray

curl -sS https://dooray.infomaxai.com/health     # {"ok": true}
```

### 테스트

```bash
python -m pytest tests -q        # 336 passed
```

---

## 문서

**[`docs/README.md`](docs/README.md)** 에서 시작하세요. 목적별로 어디부터 읽을지
정리해 두었습니다.

| | |
|---|---|
| [`docs/09-시연-흐름.html`](docs/09-시연-흐름.html) | 시연용 — 한 바퀴 전체, 그림 셋 |
| [`docs/08-두레이-연동-기술노트.html`](docs/08-두레이-연동-기술노트.html) | 공유용 — 결론과 함정 요약 |
| [`docs/08-두레이-연동-기술노트.md`](docs/08-두레이-연동-기술노트.md) | 전체 판 — 구현할 때 |
| [`docs/사용법.html`](docs/사용법.html) | 담당자용 |

HTML 문서는 브라우저로 열면 됩니다 (`open docs/09-시연-흐름.html`).

---

## 코드 구조

```
crm/         고객정보 조회 — 파서 · 마스킹 · 포매터 · HTTP 어댑터
support/     기술지원 — 추출 · LLM 보강 · 티켓 · 양식 · 접수 · 커맨드 · 완료 감지
standalone/  실행 진입점 — agent.py · command_server.py · mock_crm.py
deploy/      Dockerfile · docker-compose.yml
tests/       336개
routing.py   채널 → 핸들러 (키 집합이 곧 화이트리스트)
```

---

## 알아둘 것

- ⚠️ **CRM은 모의 서버이고 데이터는 전부 가짜입니다.** 시연 때 반드시 밝히세요.
  실 API 스펙이 나오면 `.env`의 `CRM_BASE_URL` 한 줄만 바꾸면 됩니다.
- ⚠️ 개인 액세스 토큰은 **본인과 동일한 권한**입니다. 봇 전용으로 격리되지 않습니다.
- ⚠️ 같은 토큰으로 소켓을 두 개 열 수 없습니다(`1008`). 환경별로 토큰을 분리하세요.
- 연락처 마스킹은 PoC 단계라 꺼져 있습니다(`CRM_MASK=1`로 켤 수 있음).

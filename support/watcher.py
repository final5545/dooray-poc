"""완료 감지 폴링.

Dooray는 업무 상태 변경에 대해 알림을 보내지 않는다(2026-09-02 실측).
푸시 경로를 다 확인했으나 봇 계정 하나로는 막혀 있어 폴링으로 감지한다.

  - 목록 API 1회 호출에 workflowClass가 들어 있어 건별 상세 조회가 필요 없다
  - **직전 스냅샷과 비교**하므로 폴링 주기는 지연 시간만 결정하고
    누락 여부는 결정하지 않는다. 프로세스가 죽었다 살아나도 그 사이 완료된 건을 잡는다
  - 상태 파일이 없으면 첫 실행으로 보고 **통보 없이 스냅샷만 저장**한다
    (그러지 않으면 기존 완료 건 전부에 뒤늦은 알림이 나간다)
"""
import json
import logging
import os
import threading
from dataclasses import dataclass

from .completion import CompletionReply, reply_for_task, task_url
from .repository import TicketRepository

log = logging.getLogger(__name__)

CLOSED = "closed"
REGISTERED = "registered"


@dataclass
class PollResult:
    replies: list[CompletionReply]
    seeded: bool = False        # 첫 실행이라 통보를 건너뛴 경우


def newly_closed(previous: dict[str, str], current: dict[str, str]) -> list[str]:
    """이전엔 완료가 아니었는데 지금 완료인 업무 ID.

    처음 보는 업무가 이미 완료 상태면 통보하지 않는다.
    우리가 접수한 뒤 완료된 건이 아니라, 뒤늦게 시야에 들어온 건일 수 있다
    (에이전트를 처음 띄웠을 때 프로젝트에 쌓여 있던 옛 티켓들).

    ⚠️ 이 규칙 때문에 **생성 직후 첫 폴링 전에 완료된 건**이 누락된다.
       우리가 만든 티켓은 생성 시점에 track()으로 스냅샷에 등록해 이를 막는다.
    """
    out = []
    for task_id, state in current.items():
        if state != CLOSED:
            continue
        before = previous.get(task_id)
        if before is None or before == CLOSED:
            continue
        out.append(task_id)
    return out


class StateStore:
    """스냅샷 영속화. 프로세스 재시작을 견디게 한다."""

    def __init__(self, path: str):
        self.path = path

    def load(self) -> dict[str, str] | None:
        """없으면 None (첫 실행)."""
        if not os.path.exists(self.path):
            return None
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            log.warning("상태 파일을 읽지 못해 첫 실행으로 처리합니다: %s", self.path)
            return None

    def save(self, snapshot: dict[str, str]) -> None:
        tmp = f"{self.path}.tmp"
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False)
            os.replace(tmp, self.path)      # 원자적 교체 — 중간에 죽어도 파일이 깨지지 않는다
        except OSError:
            log.exception("상태 저장 실패: %s", self.path)


class CompletionWatcher:
    """폴링 1회 = poll(). 스케줄링은 호출자 몫이다."""

    def __init__(self, tickets: TicketRepository, state: StateStore):
        self.tickets = tickets
        self.state = state
        # 폴링 스레드와 메시지 핸들러 스레드가 같은 상태 파일을 건드린다.
        self._lock = threading.Lock()

    def track(self, task_id: str, state: str = REGISTERED) -> None:
        """방금 만든 티켓을 스냅샷에 즉시 등록한다.

        생성 후 첫 폴링 전에 완료되면 폴링은 그 티켓을 '처음 보는데 이미 완료'로
        판단해 통보하지 않는다. 생성 시점에 미완료로 박아 두면 다음 폴링에서
        registered → closed 전이가 정상적으로 잡힌다.

        스냅샷이 아직 없으면(첫 폴링 전) 아무것도 하지 않는다 —
        곧 이어질 시딩이 현재 상태를 그대로 담는다.
        """
        if not task_id:
            return
        with self._lock:
            snapshot = self.state.load()
            if snapshot is None:
                return
            if task_id in snapshot:
                return
            snapshot[task_id] = state
            self.state.save(snapshot)
            log.debug("스냅샷 등록: %s=%s", task_id, state)

    def poll(self) -> PollResult:
        try:
            current = self.tickets.list_states()
        except Exception:
            log.exception("업무 목록 조회 실패 — 이번 회차 건너뜀")
            return PollResult(replies=[])

        with self._lock:
            previous = self.state.load()
            if previous is None:
                self.state.save(current)
                log.info("첫 폴링 — 스냅샷 %d건 저장 (통보 없음)", len(current))
                return PollResult(replies=[], seeded=True)

        replies = []
        for task_id in newly_closed(previous, current):
            try:
                task = self.tickets.get(task_id)
            except Exception:
                log.exception("업무 조회 실패: %s", task_id)
                continue
            reply = reply_for_task(task, task_url=task_url(self.tickets, task_id))
            if reply:
                replies.append(reply)

        # 통보 성공 여부와 무관하게 스냅샷을 갱신한다.
        # 실패분을 재시도하면 중복 통보 위험이 더 크다.
        with self._lock:
            # 폴링 도중 track()으로 들어온 티켓이 목록에 아직 안 잡혔을 수 있다.
            # 이번 조회에 없는 항목은 살려 둔다.
            merged = {**(self.state.load() or {}), **current}
            self.state.save(merged)
        return PollResult(replies=replies)

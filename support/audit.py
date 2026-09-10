"""누가 무엇을 했는지 남긴다 — 승인 사용자 확인과 감사로그.

2026-09-10 회의 결정: "승인 사용자·전용 채널 화이트리스트, 최소 필드 전송,
호출속도 제한, 감사로그와 별도 제어계층을 기본조건으로 검토."

채널 화이트리스트는 처음부터 있었다(routing.py). 그런데 **그 방에 들어온
사람이면 누구나** 고객정보를 조회할 수 있었다. 모의 데이터일 때는 넘어갈
일이었지만 실 CRM이 붙은 이상 다르다.

두 가지를 여기서 다룬다.

    승인 사용자   누가 쓸 수 있는가
    감사로그      누가 언제 무엇을 했는가

⚠️ 감사로그는 **무엇을 조회했는지**만 남기고 **조회 결과는 남기지 않는다.**
   고객 연락처가 로그 파일에 쌓이면 그 파일이 새로운 유출 경로가 된다.
"""
import json
import logging
import os
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

# 감사 사건 종류
LOOKUP = "lookup"          # 고객정보 조회
CREATE = "create"          # 업무 생성
WORKFLOW = "workflow"      # 업무 상태 변경
DENIED = "denied"          # 승인되지 않은 사용자


def parse_allowed(raw: str | None) -> set[str]:
    """'3267...,3362...' → {memberId}. 비어 있으면 빈 집합(= 제한 없음)."""
    if not raw:
        return set()
    return {p.strip() for p in str(raw).replace("\n", ",").split(",") if p.strip()}


@dataclass
class Guard:
    """승인 사용자 확인.

    allowed 가 비어 있으면 **제한하지 않는다.** 설정을 빠뜨렸다고 해서 모두를
    막아 버리면 서비스가 조용히 죽는다 — 켜는 것은 명시적인 선택이어야 한다.
    다만 그 상태를 기동 배너에 찍어 눈에 보이게 한다.
    """
    allowed: set[str]

    @property
    def enabled(self) -> bool:
        return bool(self.allowed)

    @property
    def label(self) -> str:
        return f"{len(self.allowed)}명" if self.enabled else "제한 없음 — 전원 허용"

    def permits(self, user_id: str | None) -> bool:
        if not self.enabled:
            return True
        return bool(user_id) and str(user_id) in self.allowed


DENIED_MESSAGE = (
    "이 기능은 승인된 담당자만 사용할 수 있습니다.\n"
    "사용이 필요하시면 AI부에 말씀해 주세요."
)


class AuditLog:
    """감사 기록. JSON Lines 로 한 줄씩 덧붙인다.

    한 줄이 한 사건이라 tail 로 흘려보거나 grep 으로 뒤지기 쉽고, 중간이
    깨져도 나머지를 읽을 수 있다. 운영 로그(stdout)와 섞이면 보존 주기가
    엉키므로 파일을 따로 둔다.

    경로를 주지 않으면 아무것도 쓰지 않는다 — 단위테스트와 로컬 구동에서
    파일이 생기지 않게.
    """

    def __init__(self, path: str | None = None):
        self.path = (path or "").strip() or None
        self._lock = threading.Lock()
        if self.path:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".",
                        exist_ok=True)

    @property
    def label(self) -> str:
        return self.path or "끔 — 기록하지 않음"

    def write(self, event: str, *, user: str | None = None,
              channel: str | None = None, **fields) -> dict:
        """사건 1건. 기록한 내용을 그대로 돌려준다(테스트용).

        ⚠️ fields 에 조회 **결과**를 넣지 말 것. 무엇을 찾았는지(고객번호)는
           남기되 무엇이 나왔는지(이름·연락처)는 남기지 않는다.
        """
        row = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "event": event,
            "user": user,
            "channel": channel,
            **{k: v for k, v in fields.items() if v is not None},
        }
        if not self.path:
            return row
        line = json.dumps(row, ensure_ascii=False)
        try:
            with self._lock, open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            # 기록에 실패했다고 사용자 요청을 막지는 않는다. 다만 조용히
            # 지나가면 감사로그가 비어 있는 것을 아무도 모른다.
            log.exception("감사로그 기록 실패: %s", line[:200])
        return row

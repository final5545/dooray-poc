"""Dooray 업무(Project) API 어댑터.

2026-09-02 실측으로 전 구간 동작 확인 (개인 액세스 토큰):
    GET  /project/v1/projects/{id}/workflows
    POST /project/v1/projects/{id}/posts
    POST /project/v1/projects/{id}/posts/{postId}/set-workflow

⚠️ 기획서는 현황판을 'Dooray! News'로 적고 있으나 News는 REST API가 없다(404).
   업무 보드로 대체하며, 이 차이는 인포Biz본부 합의 대상이다(03 §8 #4-1).
"""
from typing import Protocol

import requests

BASE = "https://api.dooray.com"
TIMEOUT = 10.0


class TicketRepository(Protocol):
    def get(self, post_id: str) -> dict:
        """업무 상세 조회."""
        ...

    def list_states(self) -> dict[str, str]:
        """{업무ID: workflowClass}. 완료 감지 폴링용."""
        ...

    def create(self, subject: str, body: str, cc: list[str] | None = None) -> str:
        """티켓 생성 후 postId 반환.

        cc: 참조자로 넣을 organizationMemberId 목록.
            참조자로 지정되면 담당자가 상태를 바꿀 때 Dooray가 자체 알림을 보낸다
            (프로젝트 설정 불필요 — Dooray 기본 동작).
        """
        ...


class DoorayTicketRepository:
    """실제 Dooray 프로젝트에 티켓을 등록한다."""

    def __init__(self, token: str, project_id: str, timeout: float = TIMEOUT,
                 domain: str = "infomax.dooray.com"):
        self.project_id = project_id
        self.timeout = timeout
        self.domain = domain
        self._headers = {
            "Authorization": f"dooray-api {token}",
            "Content-Type": "application/json",
        }

    def _url(self, suffix: str = "") -> str:
        return f"{BASE}/project/v1/projects/{self.project_id}{suffix}"

    def list_workflows(self) -> list[dict]:
        r = requests.get(self._url("/workflows"), headers=self._headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("result") or []

    def get(self, post_id: str) -> dict:
        """업무 상세 조회. 완료 알림을 받았을 때 본문에서 원 요청 좌표를 찾는 데 쓴다."""
        r = requests.get(self._url(f"/posts/{post_id}"), headers=self._headers,
                         timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("result") or {}

    def list_tasks(self, size: int = 100) -> list[dict]:
        """목록 1회 호출로 화면에 필요한 필드까지 전부 받는다.

        2026-09-03 실측: /posts 응답 한 건에 id·number·subject·workflowClass가
        모두 들어 있다. 건별 상세 조회(N+1)를 할 이유가 없다.
        """
        r = requests.get(self._url("/posts"), headers=self._headers,
                         params={"size": size}, timeout=self.timeout)
        r.raise_for_status()
        return [{"id": p["id"], "number": p.get("number"),
                 "subject": p.get("subject"), "workflowClass": p.get("workflowClass")}
                for p in (r.json().get("result") or []) if p.get("id")]

    def list_states(self, size: int = 100) -> dict[str, str]:
        """{업무ID: workflowClass}. 완료 감지 폴링용."""
        return {t["id"]: t["workflowClass"] for t in self.list_tasks(size)}

    def task_url(self, post_id: str) -> str:
        return f"https://{self.domain}/project/tasks/{post_id}"

    def workflow_id(self, cls: str) -> str | None:
        """class(registered/working/closed)로 워크플로 ID를 찾는다.

        이름은 프로젝트마다 다르므로(할 일/등록, 진행 중/진행) class로 찾아야 한다.
        """
        for w in self.list_workflows():
            if w.get("class") == cls:
                return w.get("id")
        return None

    def create(self, subject: str, body: str, cc: list[str] | None = None) -> str:
        payload: dict = {
            "subject": subject,
            "body": {"mimeType": "text/x-markdown", "content": body},
        }
        if cc:
            payload["users"] = {
                "cc": [{"type": "member", "member": {"organizationMemberId": m}}
                       for m in cc]
            }
        r = requests.post(self._url("/posts"), headers=self._headers,
                          json=payload, timeout=self.timeout)
        r.raise_for_status()
        return (r.json().get("result") or {}).get("id", "")

    def set_workflow(self, post_id: str, workflow_id: str) -> None:
        r = requests.post(self._url(f"/posts/{post_id}/set-workflow"),
                          headers=self._headers,
                          json={"workflowId": workflow_id}, timeout=self.timeout)
        r.raise_for_status()


class FakeTicketRepository:
    """단위테스트용. 생성된 티켓을 메모리에 쌓는다."""

    def __init__(self, rows: dict[str, dict] | None = None):
        self.created: list[tuple[str, str]] = []
        self.cc: list[list[str]] = []
        self._rows = rows or {}

    def get(self, post_id: str) -> dict:
        return self._rows.get(post_id, {})

    def list_tasks(self) -> list[dict]:
        return [{"id": k, "number": v.get("number"), "subject": v.get("subject"),
                 "workflowClass": v.get("workflowClass")} for k, v in self._rows.items()]

    def list_states(self) -> dict[str, str]:
        return {k: v.get("workflowClass") for k, v in self._rows.items()}

    def task_url(self, post_id: str) -> str:
        return f"https://example.invalid/project/tasks/{post_id}"

    def create(self, subject: str, body: str, cc: list[str] | None = None) -> str:
        self.created.append((subject, body))
        self.cc.append(list(cc or []))
        return f"fake-{len(self.created)}"

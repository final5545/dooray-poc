"""슬래시 커맨드 — 버튼으로 티켓 상태를 바꾼다.

Dooray는 업무 상태 변경에 알림을 주지 않아 폴링으로 감지하고 있다(watcher.py).
그런데 애초에 **대화방에서 버튼으로 상태를 바꾸면** 감지가 필요 없다.
클릭이 곧 우리에게 오는 요청이기 때문이다.

구조 (2026-09-03 실측 문서 기준):

    /처리 입력
      → Dooray가 우리 Request URL 로 POST
      → 미완료 티켓 목록 + [수락][완료] 버튼을 ephemeral 로 응답

    버튼 클릭
      → Dooray가 우리 Interactive Request URL 로 POST
      → 우리가 Dooray 업무 상태를 바꾸고
      → replaceOriginal 로 그 자리에서 메시지 갱신

⚠️ 이 경로는 **Dooray가 우리 서버를 호출**한다. 인바운드 엔드포인트가 필요하다.
   메신저 소켓(아웃바운드)만으로는 버튼 클릭을 받을 수 없다.
"""
from dataclasses import dataclass

# 버튼이 속한 attachment 식별자. 클릭 시 그대로 되돌아온다.
CALLBACK_TICKET = "ticket-action"

# actionValue 형식: "<동작>/<업무ID>"
ACTION_ACCEPT = "accept"
ACTION_DONE = "done"

WORKFLOW_FOR = {
    ACTION_ACCEPT: "working",
    ACTION_DONE: "closed",
}

LABEL_FOR = {
    "registered": "접수",
    "working": "진행 중",
    "closed": "완료",
}


@dataclass
class ActionRequest:
    """버튼 클릭 1건."""
    action: str          # accept | done
    task_id: str
    user_id: str | None = None
    channel_id: str | None = None
    callback_id: str | None = None


def parse_action(payload: dict) -> ActionRequest | None:
    """Dooray 인터랙션 페이로드 → ActionRequest. 우리 버튼이 아니면 None."""
    if (payload or {}).get("callbackId") != CALLBACK_TICKET:
        return None
    raw = str(payload.get("actionValue") or "")
    if "/" not in raw:
        return None
    action, task_id = raw.split("/", 1)
    if action not in WORKFLOW_FOR or not task_id:
        return None
    return ActionRequest(
        action=action,
        task_id=task_id,
        user_id=((payload.get("user") or {}).get("id")),
        channel_id=((payload.get("channel") or {}).get("id")),
        callback_id=payload.get("callbackId"),
    )


def _buttons(task_id: str, state: str) -> list[dict]:
    """현재 상태에서 가능한 전환만 버튼으로 보여준다."""
    out = []
    if state == "registered":
        out.append({"name": "ticket", "type": "button", "text": "수락",
                    "value": f"{ACTION_ACCEPT}/{task_id}", "style": "primary"})
    if state in ("registered", "working"):
        out.append({"name": "ticket", "type": "button", "text": "완료",
                    "value": f"{ACTION_DONE}/{task_id}"})
    return out


def _payload(text: str, attachments: list[dict] | None, replace: bool) -> dict:
    out: dict = {"responseType": "ephemeral", "text": text}   # 누른 사람에게만 보인다
    if attachments:
        out["attachments"] = attachments
    if replace:
        out["replaceOriginal"] = True
    return out


def build_ticket_list(tasks: list[dict], title: str = "기술지원 요청",
                      notice: str | None = None, replace: bool = False) -> dict:
    """미완료 티켓 목록 → 커맨드 응답 페이로드.

    tasks:  [{"id", "subject", "workflowClass", "number"}, ...]
    notice: 목록 위에 한 줄 덧붙인다(방금 처리한 결과 등).
    replace: 원래 메시지를 그 자리에서 갈아끼운다.
    """
    open_tasks = [t for t in tasks if t.get("workflowClass") != "closed"]
    head = [notice] if notice else []

    if not open_tasks:
        head.append("처리할 요청이 없습니다.")
        return _payload("\n".join(head), None, replace)

    head.append(f"{title} ({len(open_tasks)}건)")
    attachments = []
    for t in open_tasks:
        state = t.get("workflowClass") or "registered"
        attachments.append({
            "callbackId": CALLBACK_TICKET,
            "title": t.get("subject") or f"#{t.get('number')}",
            "text": f"현재 상태 : {LABEL_FOR.get(state, state)}",
            "actions": _buttons(str(t.get("id")), state),
        })
    return _payload("\n".join(head), attachments, replace)


def build_result(req: ActionRequest, subject: str, new_state: str,
                 actor_name: str | None = None,
                 tasks: list[dict] | None = None) -> dict:
    """상태 변경 후 원래 메시지를 그 자리에서 갱신한다.

    tasks를 주면 **목록을 다시 그려서** 돌려준다. 한 건을 처리해도 나머지가
    화면에 남아 있어야 연속으로 처리할 수 있다. 처리한 건은 상태가 바뀐 채로,
    완료된 건은 목록에서 사라진 채로 보인다.

    tasks가 None이면(목록 재조회 실패) 처리 결과만이라도 알린다.
    replaceOriginal=true 는 알림 없이 내용만 바꾼다.
    """
    label = LABEL_FOR.get(new_state, new_state)

    if tasks is not None:
        notice = f"✅ {subject} → {label}" if subject else f"✅ {label} 처리했습니다."
        if actor_name:
            notice += f"  (처리자 : {actor_name})"
        return build_ticket_list(tasks, notice=notice, replace=True)

    lines = [f"{subject}", f"→ {label} 처리했습니다."]
    if actor_name:
        lines.append(f"처리자 : {actor_name}")
    return _payload("\n".join(lines), None, replace=True)


def build_error(message: str) -> dict:
    return {"responseType": "ephemeral", "replaceOriginal": True, "text": message}

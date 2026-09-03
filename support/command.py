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

# actionValue 형식: "<동작>/<업무ID>/<누를 당시 상태>"
#
# 세 번째 칸은 **되돌리기 목적지**다. 완료 버튼은 접수에서도 진행 중에서도
# 보이므로, 되돌릴 때 어디로 갈지는 누른 시점의 상태를 실어 보내야만 안다.
# 클릭 후에 조회해 봐야 이미 바뀐 뒤라 늦는다.
ACTION_ACCEPT = "accept"
ACTION_DONE = "done"
ACTION_UNDO = "undo"

WORKFLOW_FOR = {
    ACTION_ACCEPT: "working",
    ACTION_DONE: "closed",
    # 되돌리기의 목적지는 고정이 아니다 — 버튼에 실려 온 prev_state로 간다.
}

LABEL_FOR = {
    "registered": "접수",
    "working": "진행 중",
    "closed": "완료",
}


@dataclass
class ActionRequest:
    """버튼 클릭 1건."""
    action: str                       # accept | done | undo
    task_id: str
    prev_state: str | None = None     # 누를 당시 상태 = 되돌리기 목적지
    user_id: str | None = None
    channel_id: str | None = None
    callback_id: str | None = None

    @property
    def target_state(self) -> str | None:
        """이 클릭이 만들려는 상태."""
        if self.action == ACTION_UNDO:
            return self.prev_state
        return WORKFLOW_FOR.get(self.action)


def parse_action(payload: dict) -> ActionRequest | None:
    """Dooray 인터랙션 페이로드 → ActionRequest. 우리 버튼이 아니면 None."""
    if (payload or {}).get("callbackId") != CALLBACK_TICKET:
        return None
    parts = str(payload.get("actionValue") or "").split("/")
    if len(parts) not in (2, 3):
        return None

    action, task_id = parts[0], parts[1]
    prev_state = parts[2] if len(parts) == 3 else None
    if action not in (*WORKFLOW_FOR, ACTION_UNDO) or not task_id:
        return None
    if prev_state and prev_state not in LABEL_FOR:
        return None
    # 되돌리기는 목적지 없이는 성립하지 않는다
    if action == ACTION_UNDO and not prev_state:
        return None

    return ActionRequest(
        action=action,
        task_id=task_id,
        prev_state=prev_state,
        user_id=((payload.get("user") or {}).get("id")),
        channel_id=((payload.get("channel") or {}).get("id")),
        callback_id=payload.get("callbackId"),
    )


def _btn(text: str, value: str, primary: bool = False) -> dict:
    b = {"name": "ticket", "type": "button", "text": text, "value": value}
    if primary:
        b["style"] = "primary"
    return b


def _buttons(task_id: str, state: str) -> list[dict]:
    """현재 상태에서 가능한 전환만 버튼으로 보여준다."""
    out = []
    if state == "registered":
        out.append(_btn("수락", f"{ACTION_ACCEPT}/{task_id}/{state}", primary=True))
    if state in ("registered", "working"):
        out.append(_btn("완료", f"{ACTION_DONE}/{task_id}/{state}"))
    return out


def _payload(text: str, attachments: list[dict] | None, replace: bool) -> dict:
    out: dict = {"responseType": "ephemeral", "text": text}   # 누른 사람에게만 보인다
    if attachments:
        out["attachments"] = attachments
    if replace:
        out["replaceOriginal"] = True
    return out


def build_ticket_list(tasks: list[dict], title: str = "기술지원 요청",
                      replace: bool = False) -> dict:
    """미완료 티켓 목록 → 커맨드 응답 페이로드.

    tasks:  [{"id", "subject", "workflowClass", "number"}, ...]
    replace: 원래 메시지를 그 자리에서 갈아끼운다.
    """
    open_tasks = [t for t in tasks if t.get("workflowClass") != "closed"]

    if not open_tasks:
        return _payload("처리할 요청이 없습니다.", None, replace)

    attachments = []
    for t in open_tasks:
        state = t.get("workflowClass") or "registered"
        attachments.append({
            "callbackId": CALLBACK_TICKET,
            "title": t.get("subject") or f"#{t.get('number')}",
            "text": f"현재 상태 : {LABEL_FOR.get(state, state)}",
            "actions": _buttons(str(t.get("id")), state),
        })
    return _payload(f"{title} ({len(open_tasks)}건)", attachments, replace)


def _receipt(req: ActionRequest, subject: str, new_state: str,
             actor_name: str | None) -> dict:
    """방금 처리한 것 1건 — 되돌리기 버튼을 단다.

    완료하면 목록에서 사라지므로, 잘못 눌렀을 때 붙잡을 손잡이가 여기밖에
    없다. 되돌리기 자체를 되돌리는 버튼은 달지 않는다 — 이미 목록에 다시
    나타나 있으므로 거기서 누르면 된다.
    """
    label = LABEL_FOR.get(new_state, new_state)
    mark = "↩︎" if req.action == ACTION_UNDO else "✅"
    verb = "되돌렸습니다" if req.action == ACTION_UNDO else "처리했습니다"

    lines = [f"{mark} {subject} → {label} {verb}." if subject
             else f"{mark} {label} {verb}."]
    if actor_name:
        lines.append(f"처리자 : {actor_name}")

    card: dict = {"callbackId": CALLBACK_TICKET, "text": "\n".join(lines)}
    if req.action != ACTION_UNDO and req.prev_state:
        back = LABEL_FOR.get(req.prev_state, req.prev_state)
        card["actions"] = [_btn(f"되돌리기 ({back})",
                                f"{ACTION_UNDO}/{req.task_id}/{req.prev_state}")]
    return card


def build_result(req: ActionRequest, subject: str, new_state: str,
                 actor_name: str | None = None,
                 tasks: list[dict] | None = None) -> dict:
    """상태 변경 후 원래 메시지를 그 자리에서 갱신한다.

    tasks를 주면 **목록을 다시 그려서** 돌려준다. 한 건을 처리해도 나머지가
    화면에 남아 있어야 연속으로 처리할 수 있다. 처리한 건은 상태가 바뀐 채로,
    완료된 건은 목록에서 사라진 채로 보인다.

    맨 위에는 방금 처리한 것과 되돌리기 버튼이 붙는다.

    tasks가 None이면(목록 재조회 실패) 처리 결과만이라도 알린다.
    replaceOriginal=true 는 알림 없이 내용만 바꾼다.
    """
    receipt = _receipt(req, subject, new_state, actor_name)

    if tasks is not None:
        out = build_ticket_list(tasks, replace=True)
        out["attachments"] = [receipt, *out.get("attachments", [])]
        return out

    return _payload(receipt["text"], [receipt] if receipt.get("actions") else None,
                    replace=True)


def build_error(message: str) -> dict:
    return {"responseType": "ephemeral", "replaceOriginal": True, "text": message}

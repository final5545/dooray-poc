#!/usr/bin/env python3
"""승인 사용자 명단을 관리한다.

명단은 `.env` 의 `DOORAY_ALLOWED_USERS` 한 줄이다. 값은 두레이
organizationMemberId 를 쉼표로 이은 것인데, 이 숫자를 사람이 알 방법이
마땅치 않다. 이름으로 찾아 넣고 빼는 일을 여기서 한다.

    python3 tools/승인명단.py                 지금 명단을 이름과 함께 본다
    python3 tools/승인명단.py 찾기 정원석      이름으로 memberId 를 찾는다
    python3 tools/승인명단.py 추가 정원석      명단에 넣는다
    python3 tools/승인명단.py 빼기 정원석      명단에서 뺀다

⚠️ `.env` 를 고쳐도 **돌고 있는 프로세스는 모른다.** 맥의 에이전트는 다시
   띄우고, 서버는 배포해야 반영된다. 마지막에 그 명령을 찍어 준다.

⚠️ 명단이 **비면 제한하지 않는다.** 마지막 한 사람을 빼면 전원 허용으로
   돌아간다 — 그때는 한 번 더 묻는다.
"""
import os
import pathlib
import re
import sys

import requests
from dotenv import load_dotenv

ENV = pathlib.Path(__file__).resolve().parent.parent / ".env"
KEY = "DOORAY_ALLOWED_USERS"
API = "https://api.dooray.com/common/v1/members"   # ⚠️ 사내 도메인이 아니다


def _headers():
    load_dotenv(ENV)
    token = os.getenv("DOORAY_TOKEN")
    if not token:
        raise SystemExit(f"{ENV} 에 DOORAY_TOKEN 이 없다")
    return {"Authorization": f"dooray-api {token}"}


def search(word):
    """이름 조각으로 찾는다. 두레이는 부분 일치를 지원한다."""
    r = requests.get(API, headers=_headers(),
                     params={"name": word, "size": 20}, timeout=15)
    r.raise_for_status()
    return r.json().get("result") or []


def by_ids(ids):
    """memberId 로 사람을 되찾는다. 검색 API 에 id 조회가 없어 한 명씩 본다."""
    out = {}
    h = _headers()
    for i in ids:
        try:
            r = requests.get(f"{API}/{i}", headers=h, timeout=15)
            if r.ok:
                out[i] = r.json().get("result") or {}
        except requests.RequestException:
            pass
    return out


def read_list():
    text = ENV.read_text()
    m = re.search(rf"^{KEY}=(.*)$", text, re.M)
    raw = m.group(1) if m else ""
    return [p.strip() for p in raw.split(",") if p.strip()]


def write_list(ids):
    """그 한 줄만 바꾼다. 다른 줄은 건드리지 않는다."""
    text = ENV.read_text()
    line = f"{KEY}={','.join(ids)}"
    if re.search(rf"^{KEY}=.*$", text, re.M):
        text = re.sub(rf"^{KEY}=.*$", line, text, count=1, flags=re.M)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    ENV.write_text(text)


def show(ids):
    if not ids:
        print("  명단이 비어 있다 — ⚠️ 제한하지 않는다. 채널에 들어온 사람이면 누구나 쓴다.")
        return
    people = by_ids(ids)
    print(f"  승인 사용자 {len(ids)}명")
    for i in ids:
        p = people.get(i) or {}
        name = p.get("name") or "(이름을 못 찾음)"
        code = p.get("userCode") or ""
        print(f"    {name:10} {code:14} {i}")


def pick(word):
    """한 명으로 좁힌다. 여럿이면 고르게 하고 멈춘다."""
    found = search(word)
    if not found:
        raise SystemExit(f"'{word}' 로 찾은 사람이 없다")
    if len(found) > 1:
        exact = [p for p in found if p.get("name") == word or p.get("userCode") == word]
        if len(exact) == 1:
            return exact[0]
        print(f"  '{word}' 로 {len(found)}명이 나왔다. userCode 로 다시 불러라.")
        for p in found[:20]:
            print(f"    {p.get('name'):10} {p.get('userCode'):14} {p.get('id')}")
        raise SystemExit(1)
    return found[0]


def after():
    print()
    print("  반영하려면 —")
    print("    맥   pkill -f standalone/agent.py && nohup python3 standalone/agent.py &")
    print("    서버 ssh ai-node-1 'cd ~/svc/dooray-poc && git pull && "
          "set -a && . .env && set +a && docker stack deploy -c deploy/docker-compose.yml dooray'")
    print("         ⚠️ 서버의 .env 는 따로 고쳐야 한다 — 저장소에 올라가지 않는다")


def main(argv):
    if not ENV.exists():
        raise SystemExit(f"{ENV} 가 없다")
    cmd = argv[0] if argv else "보기"
    ids = read_list()

    if cmd in ("보기", "list"):
        show(ids)
        return

    if cmd in ("찾기", "find"):
        if len(argv) < 2:
            raise SystemExit("찾을 이름을 적어라")
        found = search(argv[1])
        print(f"  '{argv[1]}' → {len(found)}명")
        for p in found:
            mark = "✓" if p.get("id") in ids else " "
            print(f"   {mark} {p.get('name'):10} {p.get('userCode'):14} {p.get('id')}")
        return

    if cmd in ("추가", "add", "빼기", "remove"):
        if len(argv) < 2:
            raise SystemExit("이름을 적어라")
        person = pick(argv[1])
        pid, name = person["id"], person.get("name")

        if cmd in ("추가", "add"):
            if pid in ids:
                print(f"  {name} 은(는) 이미 명단에 있다")
                return
            ids.append(pid)
            print(f"  + {name} ({person.get('userCode')}) {pid}")
        else:
            if pid not in ids:
                print(f"  {name} 은(는) 명단에 없다")
                return
            if len(ids) == 1:
                ans = input("  ⚠️ 마지막 한 사람이다. 빼면 전원 허용으로 돌아간다. "
                            "그래도 뺄까? (예/아니오) ")
                if ans.strip() not in ("예", "y", "Y", "yes"):
                    print("  그만둔다")
                    return
            ids.remove(pid)
            print(f"  − {name} ({person.get('userCode')}) {pid}")

        write_list(ids)
        print()
        show(ids)
        after()
        return

    raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

"""대화방 목록에서 채널 ID를 찾는다.

    export DOORAY_TOKEN=...
    python standalone/find_channel.py [검색어]
"""
import os
import sys

import requests

TOKEN = os.getenv("DOORAY_TOKEN")
BASE = "https://api.dooray.com"


def main() -> None:
    if not TOKEN:
        sys.exit("DOORAY_TOKEN 환경변수가 없습니다.")
    needle = sys.argv[1] if len(sys.argv) > 1 else ""

    r = requests.get(f"{BASE}/messenger/v1/channels",
                     headers={"Authorization": f"dooray-api {TOKEN}"},
                     timeout=20)
    print(f"HTTP {r.status_code}")
    if r.status_code != 200:
        print(r.text[:300])
        return

    rows = r.json().get("result") or []
    print(f"대화방 {len(rows)}건\n")
    for c in rows:
        title = c.get("title") or ""
        if needle and needle not in title:
            continue
        print(f"  id={c.get('id')}  type={c.get('type')!r}  "
              f"members={len(c.get('users', {}).get('members') or [])}  title={title!r}")


if __name__ == "__main__":
    main()

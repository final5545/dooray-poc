#!/usr/bin/env python3
"""HTML 문서에 글꼴을 심는다 — 파일 하나만 옮겨도 그대로 보이게.

문서를 사내에 돌리면 인터넷이 막힌 자리에서 열리는 일이 있다. 그때
Google Fonts 링크는 조용히 실패하고 제목이 시스템 글꼴로 떨어진다.
읽기는 하지만 우리가 만든 문서로 보이지는 않는다.

Google Fonts 는 ``&text=`` 로 **쓰인 글자만** 잘라 준다. 한글 글꼴 전체는
수 MB 지만 이 문서에 실제로 나오는 396자만 받으면 100KB 대다. 그것을
base64 로 문서 안에 넣는다.

    python3 tools/글꼴내장.py docs/*.html

⚠️ 문서를 고치면 글자 집합이 바뀐다. **글을 고친 뒤 다시 돌려야 한다.**
   빠진 글자는 fallback 글꼴로 떨어져 그 글자만 모양이 달라진다.

여러 번 돌려도 결과가 같다. 심어 둔 블록을 걷어내고 다시 만든다.
"""
import base64
import pathlib
import re
import subprocess
import sys
import urllib.parse

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

BEGIN = "/* ⇩ 글꼴내장.py 가 심은 블록 — 손대지 말 것"
END = "/* ⇧ 여기까지 */"

# 글꼴별로 어느 글자가 필요한지. 셀렉터가 아니라 **역할**로 적는다.
ROLES = {
    "Hahmlet": ("h1", "h2"),        # 제목에만 쓴다
    "IBM+Plex+Sans+KR": None,       # None = 문서 전체
    "IBM+Plex+Mono": None,
}


def fetch(url):
    r = subprocess.run(["curl", "-sSL", "--max-time", "40", "-A", UA, url],
                       capture_output=True)
    if r.returncode:
        raise SystemExit(f"내려받기 실패: {r.stderr.decode()[:200]}")
    return r.stdout


def strip_tags(html):
    return re.sub(r"<[^>]+>", " ", html)


def chars_used(body, tags):
    """tags 가 None 이면 문서 전체, 아니면 그 요소 안의 글자만."""
    if tags is None:
        text = strip_tags(body)
    else:
        pat = "|".join(tags)
        text = "".join(strip_tags(m.group(0)) for m in
                       re.finditer(rf"<({pat})[^>]*>.*?</\1>", body, re.S))
    return "".join(sorted({c for c in text if c.strip() and ord(c) > 31}))


def subset_css(family, text):
    """쓰인 글자만 담은 @font-face. woff2 는 data URI 로 바꿔 넣는다."""
    url = ("https://fonts.googleapis.com/css2?family=" + family
           + "&text=" + urllib.parse.quote(text, safe="") + "&display=swap")
    css = fetch(url).decode()
    if "@font-face" not in css:
        raise SystemExit(f"{family}: 서브셋을 받지 못했다\n{css[:200]}")

    # 서브셋 URL 에는 .woff2 확장자가 없다. gstatic 호스트로 잡는다.
    got = 0
    for u in re.findall(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", css):
        blob = fetch(u)
        if blob[:4] != b"wOF2":
            raise SystemExit(f"{family}: woff2 가 아니다 ({blob[:8]!r})")
        got += len(blob)
        css = css.replace(u, "data:font/woff2;base64,"
                          + base64.b64encode(blob).decode())
    if not got:
        raise SystemExit(f"{family}: 글꼴 파일을 찾지 못했다")
    return css, got


def families_of(html):
    """이미 심었으면 심을 때 적어 둔 목록을, 아니면 link 에서 읽는다."""
    mark = re.search(re.escape(BEGIN) + r"\s*:\s*([^\n]+?)\s*\*/", html)
    if mark:
        return mark.group(1).split("|")
    return re.findall(r"family=([^&\"]+)", html)


def unembed(html):
    """심어 둔 블록과 남은 link 를 걷어낸다."""
    html = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\s*",
                  "", html, flags=re.S)
    html = re.sub(r'<style>\s*</style>\s*', "", html)
    html = re.sub(r'<link[^>]*fonts\.(?:googleapis|gstatic)\.com[^>]*>\s*',
                  "", html)
    return html


def embed(path):
    p = pathlib.Path(path)
    html = p.read_text()
    families = families_of(html)
    if not families:
        print(f"  건너뜀  {p.name} — 쓰는 글꼴이 없다")
        return

    html = unembed(html)
    body = html[html.find("</style>"):]
    body = re.sub(r'src="data:[^"]+"', "", body)     # 그림은 글자가 아니다

    blocks, total = [], 0
    for fam in families:
        name = fam.split(":")[0]
        text = chars_used(body, ROLES.get(name))
        if not text:
            continue
        css, size = subset_css(fam, text)
        blocks.append(css)
        total += size
        print(f"       {name:24} {len(text):4}자 {size / 1024:7.1f} KB")

    style = (f"<style>\n{BEGIN} : {'|'.join(families)} */\n"
             + "\n".join(blocks) + f"\n{END}\n</style>\n")

    # <title> 뒤에 넣는다 — 문서 스타일보다 먼저 와야 한다
    at = html.find("<title>")
    at = html.index("\n", at) + 1 if at >= 0 else 0
    p.write_text(html[:at] + style + html[at:])
    print(f"  ✓ {p.name}  글꼴 {total / 1024:.0f} KB → 문서 "
          f"{p.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for arg in sys.argv[1:]:
        embed(arg)

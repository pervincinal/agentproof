#!/usr/bin/env python3
"""`EXAMPLE-client-report.md` -> `site/sample-report.html`.

NİYƏ SKRİPT, NİYƏ ƏL İLƏ YOX: nümunə hesabat saytın ən güclü sübutudur —
alıcı bizi işə götürməzdən əvvəl məhsulun özünü oxuyur. Əl ilə köçürülmüş
HTML markdown-dan geri qalar və biz bunu fərq etmərik. Skript ikisini
bağlayır, `test_sample_report.py` isə sinxronluğu qoruyur.

CSP QEYDİ: sayt `script-src 'none'` və inline stil qadağası ilə verilir
(`render.yaml`), ona görə burada nə `<script>`, nə `style="..."` yazılır.
Bütün görünüş `/style.css` + `/report.css`-dədir.

    python3 site/build_sample.py [--check]
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

from markdown_it import MarkdownIt

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "templates" / "EXAMPLE-client-report.md"
OUTPUT = ROOT / "site" / "sample-report.html"

HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sample audit report — AgentProof</title>
<meta name="description" content="A complete audit report, exactly as a client receives it. Every figure comes from a run artifact.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Libre+Franklin:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="/style.css">
<link rel="stylesheet" href="/report.css">
</head>
<body>

<nav class="nav">
  <div class="wrap">
    <a class="brand" href="/">AgentProof</a>
    <ul>
      <li><a href="/#method">Method</a></li>
      <li><a href="/#pricing">Pricing</a></li>
      <li><a href="/sample-report">Sample report</a></li>
      <li><a href="/rules">Rules of engagement</a></li>
      <li><a href="https://github.com/pervincinal/agentproof">Code</a></li>
    </ul>
  </div>
</nav>

<div class="wrap">
<div class="sample-note">
  <span class="lab">What this is</span>
  <p>A complete audit report, in the form a client receives it. The client here
  is Aurora Goods, a support agent we built ourselves so that the ground truth
  would be knowable — §2.2 says so in the report itself rather than in a
  footnote. Every figure traces to a run artifact in
  <a href="https://github.com/pervincinal/agentproof">the repository</a>.
  It is written in Azerbaijani; client reports are written in the client's
  language.</p>
</div>
<article class="report" lang="az">
"""

FOOT = """</article>
</div>

<footer>
  <div class="wrap">
    <span>AgentProof — independent audits of AI agents.</span>
    <span>Harness and findings released under Apache&nbsp;2.0 · <a href="/">Home</a></span>
  </div>
</footer>

</body>
</html>
"""


def render() -> str:
    text = SOURCE.read_text()
    # Mənbədəki HTML şərhi daxili qeyddir — dərc olunan səhifəyə düşmür.
    text = re.sub(r"^<!--.*?-->\s*", "", text, count=1, flags=re.S)
    md = MarkdownIt("commonmark").enable(["table", "strikethrough"])
    body = md.render(text)
    # markdown-it cədvəl düzləndirməsini inline stil kimi yazır, CSP isə inline
    # stili bloklayır (`render.yaml`). Məna itməsin deyə sinifə çevrilir —
    # rəqəm sütunlarının sağa düzlənməsi hesabatda oxunuşu daşıyır.
    body = body.replace(' style="text-align:right"', ' class="ta-r"')
    body = body.replace(' style="text-align:center"', ' class="ta-c"')
    body = body.replace(' style="text-align:left"', ' class="ta-l"')
    if 'style="' in body:
        raise SystemExit(
            "inline stil qaldı — CSP onu bloklayacaq, çevirməni genişləndir:\n"
            + "\n".join(sorted({m for m in __import__("re").findall(r'style=\"[^\"]*\"', body)}))
        )
    return HEAD + body + FOOT


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="yazma — sadəcə sinxronluğu yoxla")
    args = ap.parse_args(argv)

    built = render()
    if args.check:
        if not OUTPUT.exists():
            print(f"{OUTPUT}: YOXDUR — `python3 site/build_sample.py` qaçır", file=sys.stderr)
            return 1
        if OUTPUT.read_text() != built:
            print(f"{OUTPUT}: mənbədən GERİ QALIB — yenidən qur", file=sys.stderr)
            return 1
        print(f"{OUTPUT}: sinxrondur")
        return 0

    OUTPUT.write_text(built)
    print(f"{OUTPUT}: {len(built):,} bayt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

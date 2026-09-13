#!/usr/bin/env python3
"""Ön-audit qaralamasından MÜŞTƏRİ nüsxəsi və PDF qurur.

Qaralamanın başındakı `<!-- … -->` bloku daxili yoxlama siyahısıdır — alıcıya
getməməlidir. Bu skript onu kəsir, sitatları artefaktla yoxlayır (uyğunsuzluq
varsa DAYANIR), sonra Chrome headless ilə PDF çap edir və PDF-in mətnini
yenidən oxuyub daxili qeydin sızmadığını təsdiqləyir.

    python3 evals/render_onepager.py preaudit/acorn/ONEPAGER-DRAFT.md \\
        preaudit/acorn/merged/merged.json --name AgentProof-Acorn-preaudit
"""

from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import sys

from markdown_it import MarkdownIt

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CSS = """
@page { size: A4; margin: 18mm 17mm; }
* { box-sizing: border-box; }
body { font: 10.5pt/1.5 -apple-system, "Helvetica Neue", Arial, sans-serif;
       color: #16191a; margin: 0; }
h1 { font-size: 19pt; line-height: 1.2; margin: 0 0 12pt; letter-spacing: -.01em; }
h2 { font-size: 13pt; margin: 20pt 0 6pt; padding-top: 8pt;
     border-top: 1px solid #cfd3d0; page-break-after: avoid; }
h3 { font-size: 11pt; margin: 14pt 0 5pt; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
p { margin: 0 0 7pt; }
ul { margin: 0 0 8pt; padding-left: 16pt; }
li { margin-bottom: 3pt; }
hr { border: 0; margin: 6pt 0; }
blockquote { margin: 6pt 0; padding: 2pt 0 2pt 10pt; border-left: 2px solid #9aa19d;
             color: #3d4441; page-break-inside: avoid; }
blockquote p { margin: 0 0 4pt; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt;
        font-size: 9.5pt; page-break-inside: avoid; }
th, td { text-align: left; vertical-align: top; padding: 4pt 7pt 4pt 0;
         border-bottom: 1px solid #e1e4e2; }
th { font-weight: 600; color: #50575a; border-bottom: 1px solid #b9bfbc; }
code { font: 9pt ui-monospace, Menlo, monospace; }
strong { font-weight: 650; }
"""


def strip_internal(md: str) -> str:
    return re.sub(r"\A\s*<!--.*?-->\s*", "", md, count=1, flags=re.S)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("draft")
    ap.add_argument("record")
    ap.add_argument("--name", required=True, help="çıxış faylının adı, uzantısız")
    args = ap.parse_args(argv)

    draft = pathlib.Path(args.draft)
    out_dir = draft.parent
    client_md = out_dir / f"{args.name}.md"
    client_html = out_dir / f"{args.name}.html"
    client_pdf = out_dir / f"{args.name}.pdf"

    body = strip_internal(draft.read_text())
    if "<!--" in body:
        raise SystemExit("⛔ daxili şərh bloku hələ də mətndədir")
    client_md.write_text(body)

    # 1 · sitat yoxlaması — uyğunsuzluq varsa PDF QURULMUR
    check = subprocess.run(
        [sys.executable, str(ROOT / "evals" / "verify_quotes.py"), str(client_md), args.record],
        capture_output=True, text=True,
    )
    print(check.stdout.strip())
    if check.returncode != 0:
        print(check.stderr, file=sys.stderr)
        raise SystemExit("⛔ sitat uyğunsuzluğu — PDF qurulmadı")

    # 2 · HTML
    md = MarkdownIt("commonmark").enable(["table", "strikethrough"])
    title = re.search(r"^# (.+)$", body, re.M)
    client_html.write_text(
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{title.group(1) if title else args.name}</title>"
        f"<style>{CSS}</style></head><body>{md.render(body)}</body></html>"
    )

    # 3 · PDF
    if not pathlib.Path(CHROME).exists():
        raise SystemExit(f"⛔ Chrome tapılmadı: {CHROME}")
    subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
         "--print-to-pdf-no-header", f"--print-to-pdf={client_pdf}",
         client_html.resolve().as_uri()],
        check=True, capture_output=True, timeout=90,
    )

    # 4 · PDF-i geri oxu — daxili qeyd sızmayıbmı
    if shutil.which("pdftotext"):
        text = subprocess.run(["pdftotext", "-layout", str(client_pdf), "-"],
                              capture_output=True, text=True).stdout
        pages = subprocess.run(["pdfinfo", str(client_pdf)], capture_output=True, text=True).stdout
        leaked = [w for w in ("QARALAMA", "PARVİN YOXLAYIR", "verify_quotes", "merge-6d6854") if w in text]
        if leaked:
            raise SystemExit(f"⛔ PDF-də daxili mətn var: {leaked}")
        n = re.search(r"Pages:\s+(\d+)", pages)
        print(f"PDF: {client_pdf} · {n.group(1) if n else '?'} səhifə · daxili qeyd sızmayıb ✅")
    else:
        print(f"PDF: {client_pdf} (pdftotext yoxdur — geri oxunmadı)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

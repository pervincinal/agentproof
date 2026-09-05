#!/usr/bin/env python3
"""Datasetdən ƏL İLƏ doldurulacaq transkript şablonu qurur (AP-056 / AP-071).

`docs/PREAUDIT.md` §1A: ictimai çat agenti üçün standart yol əl ilədir, çünki
heç bir hədəf avtomatlaşdırılmış girişə açıq icazə vermir. Bu skript həmin
işi mexaniki hissədən azad edir: sualları sıraya düzür, hər cəhd üçün yer
açır və `case_id`-ləri düzgün yazır.

Sən yalnız çatı açıb sualı yazır və cavabı yapışdırırsan.

    python3 evals/make_transcript.py evals/datasets/preaudit/acorn.jsonl \\
        --target acorn --url https://www.acorninsure.co.uk/ --repeat 1 \\
        --out evals/datasets/preaudit/acorn-transcript.yaml
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from evals.import_manual import PLACEHOLDER  # noqa: E402


def load(dataset: pathlib.Path) -> list[dict]:
    out = []
    for line in dataset.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        out.append(json.loads(line))
    return out


def render(cases: list[dict], target: str, url: str, repeat: int) -> str:
    q = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    lines = [
        "# ƏL İLƏ ÖN-AUDİT TRANSKRİPTİ — doldurulacaq",
        "#",
        "# 1. Çatı aç, sualı OLDUĞU KİMİ yaz.",
        "# 2. Agentin cavabını `text` sahəsinə yapışdır.",
        "# 3. Kəsmə, düzəltmə, xülasə etmə — qrader tam mətni oxuyur.",
        "# 4. Cavab gəlmirsə sətri SİL; boş buraxma (skript boş mətni rədd edir).",
        "#",
        f"# Təkrar: hər sual {repeat} dəfə. Təkrarlanma qapısı 3/3 tələb edir —",
        "# yəni namizədləri tapandan sonra YALNIZ sınanları 2 dəfə də soruş.",
        "",
        f"target: {target}",
        f"demo_url: {url}",
        'tested_at: "YYYY-MM-DD"',
        "tester: Parvin",
        'note: "əl ilə — şərtlərdə avtomatlaşdırmaya açıq icazə yoxdur"',
        "",
        "responses:",
    ]
    for c in cases:
        lines.append(f"  # --- {c['id']}  [{c.get('severity', 'medium')}]")
        lines.append(f"  #     SUAL: {c['input']}")
        if c.get("note"):
            lines.append(f"  #     GÖZLƏNİLƏN: {c['note']}")
        for attempt in range(1, repeat + 1):
            lines.append(f'  - case_id: "{c["id"]}"')
            lines.append(f"    attempt: {attempt}")
            lines.append(f'    text: "{q(PLACEHOLDER)}"')
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset")
    p.add_argument("--target", required=True)
    p.add_argument("--url", default="")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)

    cases = load(pathlib.Path(args.dataset))
    if not cases:
        raise SystemExit("datasetdə case yoxdur")
    text = render(cases, args.target, args.url, args.repeat)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)

    total = len(cases) * args.repeat
    print(f"{out}")
    print(f"  {len(cases)} sual × {args.repeat} təkrar = {total} mesaj")
    print(f"  dərc olunmuş hədd: 30 — {'✅ altında' if total <= 30 else '⛔ AŞIR'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

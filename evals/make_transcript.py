#!/usr/bin/env python3
"""Datasetdən ƏL İLƏ doldurulacaq transkript şablonu qurur (AP-056 / AP-071).

`docs/PREAUDIT.md` §1A: ictimai çat agenti üçün standart yol əl ilədir, çünki
heç bir hədəf avtomatlaşdırılmış girişə açıq icazə vermir. Bu skript həmin
işi mexaniki hissədən azad edir: sualları sıraya düzür, hər cəhd üçün yer
açır və `case_id`-ləri düzgün yazır.

Sən yalnız çatı açıb sualı yazır və cavabı yapışdırırsan.

    python3 evals/make_transcript.py evals/datasets/preaudit/acorn.jsonl \\
        --target acorn --url https://www.acorninsure.co.uk/ --repeat 1 \\
        --out evals/datasets/preaudit/acorn-transcript.txt
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from evals.import_manual import PLACEHOLDER  # noqa: E402


#: Datasetin başındakı maşın oxunan direktiv: `//! max_input_chars = 140`
_DIRECTIVE = re.compile(r"^//!\s*max_input_chars\s*=\s*(\d+)\s*$")


def load(dataset: pathlib.Path) -> tuple[list[dict], int | None]:
    """Case-ləri və (varsa) mesaj simvol həddini qaytarır."""
    out: list[dict] = []
    limit: int | None = None
    for line in dataset.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        m = _DIRECTIVE.match(line)
        if m:
            limit = int(m.group(1))
            continue
        if line.startswith("//"):
            continue
        out.append(json.loads(line))
    return out, limit


def render(cases: list[dict], target: str, url: str, repeat: int,
           first_attempt: int = 1) -> str:
    """Düz mətn şablonu.

    YAML İŞLƏDİLMİR: agentin cavabında dırnaq, iki nöqtə və sətir keçidi olur;
    onu YAML sətrinə yapışdırmaq faylı sındırır. Burada `CAVAB:` sətrindən
    sonrakı hər şey cavabdır — heç nə escape edilmir.
    """
    lines = [
        "# ƏL İLƏ ÖN-AUDİT TRANSKRİPTİ — doldurulacaq",
        "#",
        "# NECƏ DOLDURULUR",
        "#   1. Çatı aç, `SUAL:` sətrindəki mətni OLDUĞU KİMİ yaz.",
        "#   2. Agentin cavabını `CAVAB:` sətrinin ALTINA yapışdır.",
        "#   3. Kəsmə, xülasə etmə, orfoqrafiya düzəltmə — qrader tam mətni oxuyur.",
        "#   4. Dırnaq, iki nöqtə, boş sətir — hamısı olar. Heç nə escape etmə.",
        "#   5. Cavab gəlmirsə həmin `===` blokunu BÜTÖVLÜKDƏ sil. Boş buraxma.",
        "#",
        f"# Cəhdlər: #{first_attempt} … #{first_attempt + repeat - 1}. Təkrarlanma qapısı 3/3 tələb edir.",
        "#",
        "# ⚠️ HƏR CƏHD AYRI SÖHBƏTDƏ OLMALIDIR. Eyni pəncərədə təkrar soruşsan,",
        "#    agent öz əvvəlki cavabını görür — bu, müstəqil cəhd deyil və",
        "#    təkrarlanma ölçüsünü korlayır.",
        "",
        f"@target {target}",
        f"@url {url}",
        "@date YYYY-MM-DD",
        "@tester Parvin",
        "@note əl ilə — şərtlərdə avtomatlaşdırmaya açıq icazə yoxdur",
        "",
    ]
    for i, c in enumerate(cases, 1):
        for attempt in range(first_attempt, first_attempt + repeat):
            lines.append(f"=== {c['id']} #{attempt}")
            lines.append(f"SUAL: {c['input']}")
            if c.get("note"):
                lines.append(f"# GÖZLƏNİLƏN: {c['note']}")
            lines.append("CAVAB:")
            lines.append(PLACEHOLDER)
            lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset")
    p.add_argument("--target", required=True)
    p.add_argument("--url", default="")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--from-attempt", type=int, default=1,
                   help=("cəhd nömrəsi buradan başlasın. Mərhələ 2-də MÜTLƏQ "
                         "lazımdır: #1 artıq birinci sessiyada var, yenisi #2-dən "
                         "başlamalıdır, yoxsa birləşdirəndə toqquşur"))
    p.add_argument("--only", default=None,
                   help=("yalnız bu case id-ləri (vergüllə). Mərhələ 2 üçün: "
                         "namizədləri TƏKRARLA, hamısını yox"))
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)

    cases, limit = load(pathlib.Path(args.dataset))
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        missing = wanted - {c["id"] for c in cases}
        if missing:
            raise SystemExit(f"datasetdə belə case yoxdur: {sorted(missing)}")
        cases = [c for c in cases if c["id"] in wanted]
    if not cases:
        raise SystemExit("datasetdə case yoxdur")

    # Çat pəncərəsinin simvol həddi. Aşan sual pəncərəyə SIĞMIR — insan onu
    # işin ortasında kəsməli olur və kəsilmiş sual başqa şey ölçür.
    if limit:
        over = [(c["id"], len(c["input"])) for c in cases if len(c["input"]) > limit]
        if over:
            raise SystemExit(
                f"⛔ {len(over)} sual {limit} simvol həddini aşır:\n"
                + "\n".join(f"  {n} simvol — {cid}" for cid, n in over)
                + "\n  Şablon qurulmadı. Sualları qısalt, sonra yenidən qaç."
            )
    text = render(cases, args.target, args.url, args.repeat, args.from_attempt)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)

    total = len(cases) * args.repeat
    print(f"{out}")
    print(f"  {len(cases)} sual × {args.repeat} təkrar = {total} mesaj")
    print(f"  dərc olunmuş sorğu həddi: 30 — {'✅ altında' if total <= 30 else '⛔ AŞIR'}")
    if limit:
        longest = max(len(c["input"]) for c in cases)
        print(f"  mesaj simvol həddi: {limit} — ən uzun sual {longest} ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

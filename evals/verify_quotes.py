#!/usr/bin/env python3
"""Müştəri sənədindəki hər agent sitatı artefaktda VARMI (AP-057).

NİYƏ VAR. Uydurulmuş və ya «təmizlənmiş» sitat müştəri hesabatında edilə
biləcək ən ağır səhvdir: bir cümlə yanlış köçürülsə, hesabatın qalanı da
etibarını itirir. Əl ilə köçürmə isə məhz bunu asanlaşdırır — bir söz düşür,
bir tire dəyişir, mətn «səliqəli» olur.

NECƏ İŞLƏYİR. Sənəddə cəhd cədvəllərini axtarır:

    | 2 | *"You should report any incident … within 24 hours."* |

Sətrin başındakı rəqəm cəhd nömrəsidir; dırnaq içindəki mətn həmin cəhdin
cavabında **hərfbəhərf** olmalıdır. Kəsilmə `…` və ya `...` ilə göstərilirsə,
parça-parça yoxlanılır.

NƏYİ YOXLAMIR. Şirkətin öz saytından gətirilən sitatlar (bloklu sitat
şəklində) artefaktda olmur — onlar yoxlanılmır. Onları insan mənbədən
təsdiqləyir.

    python3 evals/verify_quotes.py preaudit/acorn/ONEPAGER-DRAFT.md \\
        preaudit/acorn/merged/merged.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

#: `| 2 | *"mətn"* |` — cəhd cədvəlinin sətri.
_ROW = re.compile(r'^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*$')
#: Sətir daxilində dırnağa alınmış hissə.
_QUOTED = re.compile(r'\*"(.+?)"\*|["“](.+?)["”]')
#: Kəsilmə markerləri.
_ELLIPSIS = re.compile(r"\s*(?:…|\.\.\.)\s*")


def _norm(text: str) -> str:
    text = text.replace("**", "").replace("*", "")
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("—", "—").replace("–", "–")
    return re.sub(r"\s+", " ", text).strip().lower()


def load_responses(record: pathlib.Path) -> dict[tuple[str, int], str]:
    data = json.loads(record.read_text())
    out: dict[tuple[str, int], str] = {}
    for r in data.get("results", []):
        out[(r["case_id"], int(r["attempt"]))] = _norm(r["response"]["text"])
    return out


def extract(doc: str) -> list[tuple[int, str]]:
    """Cəhd cədvəllərindən (cəhd nömrəsi, sitat) cütləri."""
    found: list[tuple[int, str]] = []
    for line in doc.splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        attempt, cell = int(m.group(1)), m.group(2)
        for q in _QUOTED.finditer(cell):
            text = q.group(1) or q.group(2)
            if text and len(text) > 20:
                found.append((attempt, text))
    return found


def check(quote: str, haystacks: list[str]) -> bool:
    """Kəsilmiş sitat parçalarının HAMISI eyni cavabda, SIRA ilə olmalıdır."""
    parts = [_norm(p) for p in _ELLIPSIS.split(quote) if _norm(p)]
    for hay in haystacks:
        pos, ok = 0, True
        for part in parts:
            i = hay.find(part, pos)
            if i < 0:
                ok = False
                break
            pos = i + len(part)
        if ok:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("document")
    p.add_argument("record")
    args = p.parse_args(argv)

    doc = pathlib.Path(args.document).read_text()
    responses = load_responses(pathlib.Path(args.record))
    quotes = extract(doc)

    if not quotes:
        print("⚠️  sənəddə cəhd cədvəli tapılmadı — yoxlanacaq sitat yoxdur",
              file=sys.stderr)
        return 1

    bad = []
    for attempt, quote in quotes:
        pool = [t for (_cid, a), t in responses.items() if a == attempt]
        if not check(quote, pool):
            bad.append((attempt, quote))

    for attempt, quote in bad:
        print(f"⛔ cəhd #{attempt} — artefaktda TAPILMADI:\n   {quote[:120]}",
              file=sys.stderr)

    print(f"{len(quotes)} sitat yoxlanıldı · {len(quotes) - len(bad)} təsdiqləndi"
          + (f" · {len(bad)} UYĞUNSUZ" if bad else " ✅"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

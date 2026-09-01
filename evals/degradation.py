#!/usr/bin/env python3
"""Çoxnövbəli DEQRADASİYA ƏYRİSİ — «neçənci növbədə sınır?» (AP-017).

NİYƏ. `docs/FAILURE-TAXONOMY.md` C1 rejimi ICLR 2026 işinə istinad edir:
çoxnövbəli söhbətdə orta **39% düşmə**. Mövcud C1 case-lərimiz sınmanın
FAKTINI verir, `failure-onset turn`-ü yox — yəni «sistem çoxnövbəlidə pisdir»
deyə bilirik, «5-ci növbədən sonra sınır» deyə bilmirik. Birincisi hesabat
cümləsidir, ikincisi düzəliş göstərişidir.

NECƏ ÖLÇÜLÜR. `evals/datasets/build_full.py → CURVE_FAMILIES` eyni sualı 1, 3,
5 və 8 növbəlik söhbətlərdə verir. Faktlar həmişə BİRİNCİ mesajdadır, sual
həmişə SONUNCUDA, iynə eynidir; dəyişən yalnız aralarındakı məzmunsuz
növbələrin sayıdır. Ona görə iki ölçü arasındakı fərqi başqa heç nə izah edə
bilməz.

    failure-onset(ailə) = case-in İLK dəfə sındığı növbə sayı

İstifadə:
    python evals/degradation.py reports/<run_id>
    python evals/degradation.py reports/<run_id> --json curve.json
    python evals/degradation.py reports/a reports/b     # qaçışları birləşdir

Nə iddia ETMİRİK: bu, bir qaçışın ölçüsüdür. `--repeat N` ilə hər nöqtə N
müstəqil cavabdan gəlir və keçmə DƏRƏCƏSİ hesablanır; N kiçikdirsə əyri
səs-küylüdür və bunu gizlətmirik (çıxışda `n=` sütunu var).
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

CURVE_TAG = "degradation-curve"
_FAMILY_RE = re.compile(r"^curve-(.+)$")
_TURNS_RE = re.compile(r"^turns-(\d+)$")


@dataclass
class Point:
    """Bir ailənin bir növbə sayındakı ölçüsü."""

    turns: int
    attempts: int = 0
    passed: int = 0
    skipped: int = 0
    case_ids: list[str] = field(default_factory=list)
    #: Növbə-növbə cavab mətnlərinin uzunluğu — kontekstin harada itdiyini
    #: gözlə görmək üçün (adapter `AgentResponse.turns` saxlayır).
    turn_text_lengths: list[int] = field(default_factory=list)

    @property
    def graded(self) -> int:
        return self.attempts - self.skipped

    @property
    def pass_rate(self) -> float | None:
        return self.passed / self.graded if self.graded else None


@dataclass
class Family:
    name: str
    points: dict[int, Point] = field(default_factory=dict)

    @property
    def onset(self) -> int | None:
        """İLK sınan növbə sayı. Heç sınmırsa `None`.

        `pass_rate < 1.0` sınma sayılır: `--repeat` ilə qismən sınma da
        sınmadır — «bəzən düzgün cavab verir» istehsalat üçün keçmiş deyil.
        """
        for n in sorted(self.points):
            rate = self.points[n].pass_rate
            if rate is not None and rate < 1.0:
                return n
        return None

    @property
    def measured(self) -> bool:
        """Heç olmasa bir nöqtə QİYMƏTLƏNDİRİLDİmi.

        Ölçülməmiş ailəni «sınmadı» yazmaq YALANÇI YAŞILdır — infrastruktur
        xətası ilə sıfır sınma arasındakı fərq hesabatın ən vacib fərqidir.
        """
        return any(p.graded for p in self.points.values())

    @property
    def baseline(self) -> float | None:
        p = self.points.get(min(self.points)) if self.points else None
        return p.pass_rate if p else None


@dataclass
class Curve:
    families: dict[str, Family] = field(default_factory=dict)
    runs: list[str] = field(default_factory=list)

    @property
    def turn_counts(self) -> list[int]:
        return sorted({n for f in self.families.values() for n in f.points})

    def aggregate(self) -> dict[int, tuple[float | None, int, int]]:
        """növbə sayı → (orta keçmə dərəcəsi, qiymətləndirilmiş, ailə sayı)."""
        out: dict[int, tuple[float | None, int, int]] = {}
        for n in self.turn_counts:
            rates = [f.points[n].pass_rate for f in self.families.values()
                     if n in f.points and f.points[n].pass_rate is not None]
            graded = sum(f.points[n].graded for f in self.families.values()
                         if n in f.points)
            out[n] = (sum(rates) / len(rates) if rates else None, graded, len(rates))
        return out

    def drop_vs_first(self) -> dict[int, float | None]:
        """İLK nöqtəyə görə mütləq düşmə — ICLR işindəki 39% ilə müqayisə üçün."""
        agg = self.aggregate()
        if not agg:
            return {}
        first = agg[min(agg)][0]
        return {n: (None if first is None or r is None else first - r)
                for n, (r, _, _) in agg.items()}


# ---------------------------------------------------------------------------
# Hesabat oxuma
# ---------------------------------------------------------------------------
def _report_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    skip = {"reproduction.json"}
    return sorted(p for p in path.glob("*.json") if p.name not in skip)


def _grade(row: dict[str, Any]) -> dict[str, Any]:
    g = row.get("grade")
    return g if isinstance(g, dict) else {}


def _turn_lengths(row: dict[str, Any]) -> list[int]:
    resp = row.get("response")
    if not isinstance(resp, dict):
        return []
    turns = resp.get("turns") or []
    return [len(t.get("text") or "") for t in turns if isinstance(t, dict)]


def load(paths: Iterable[Path]) -> Curve:
    curve = Curve()
    for root in paths:
        for f in _report_files(Path(root)):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            results = doc.get("results")
            if not isinstance(results, list):
                continue
            curve.runs.append(doc.get("run_id") or f.stem)
            for row in results:
                tags = row.get("tags") or []
                if CURVE_TAG not in tags:
                    continue
                family = next((m.group(1) for t in tags if (m := _FAMILY_RE.match(t))), None)
                turns = next((int(m.group(1)) for t in tags if (m := _TURNS_RE.match(t))), None)
                if family is None or turns is None:
                    continue
                fam = curve.families.setdefault(family, Family(family))
                pt = fam.points.setdefault(turns, Point(turns))
                grade = _grade(row)
                attempts = int(row.get("attempt") or 1)
                pt.attempts += attempts
                if grade.get("skipped"):
                    pt.skipped += attempts
                elif grade.get("passed"):
                    # `attempt` təkrar sayıdır; qismən keçmə `score`-da qalır.
                    pt.passed += attempts if grade.get("score", 1.0) >= 1.0 else \
                        round(attempts * float(grade.get("score") or 0.0))
                pt.case_ids.append(str(row.get("case_id")))
                pt.turn_text_lengths = _turn_lengths(row) or pt.turn_text_lengths
    return curve


# ---------------------------------------------------------------------------
# Çıxış
# ---------------------------------------------------------------------------
def render(curve: Curve) -> str:
    if not curve.families:
        return ("Deqradasiya əyrisi case-i tapılmadı "
                f"(`{CURVE_TAG}` teqi olan nəticə yoxdur).")
    counts = curve.turn_counts
    lines = [f"QAÇIŞ(LAR): {', '.join(curve.runs)}",
             f"AİLƏ: {len(curve.families)} · NÖVBƏ NÖQTƏLƏRİ: {counts}", ""]

    head = "ailə".ljust(34) + "".join(f"{'t' + str(n):>10}" for n in counts) + "   onset"
    lines.append(head)
    lines.append("-" * len(head))
    for name in sorted(curve.families):
        fam = curve.families[name]
        row = name[:33].ljust(34)
        for n in counts:
            pt = fam.points.get(n)
            if pt is None or pt.pass_rate is None:
                row += f"{'—':>10}"
            else:
                row += f"{pt.pass_rate:>9.0%}"
                row += "*" if pt.skipped else " "
        onset = fam.onset
        row += ("   ölçülmədi" if not fam.measured
                else f"   {'t' + str(onset) if onset else 'sınmadı'}")
        lines.append(row)

    lines.append("-" * len(head))
    agg = curve.aggregate()
    drops = curve.drop_vs_first()
    row = "ORTA".ljust(34)
    for n in counts:
        rate = agg[n][0]
        row += f"{'—':>10}" if rate is None else f"{rate:>9.0%} "
    lines.append(row)
    row = "İLK NÖQTƏYƏ GÖRƏ DÜŞMƏ".ljust(34)
    for n in counts:
        d = drops.get(n)
        row += f"{'—':>10}" if d is None else f"{d:>9.0%} "
    lines.append(row)
    row = "qiymətləndirilən cavab (n)".ljust(34)
    for n in counts:
        row += f"{agg[n][1]:>9d} "
    lines.append(row)

    lines.append("")
    measured = [f for f in curve.families.values() if f.measured]
    onsets = [f.onset for f in measured if f.onset is not None]
    if not measured:
        lines.append(f"failure-onset: ÖLÇÜLMƏDİ — {len(curve.families)} ailənin "
                     f"heç birində qiymətləndirilmiş cavab yoxdur "
                     f"(infrastruktur xətası). Bu, «sınmadı» DEYİL.")
    elif onsets:
        lines.append(f"failure-onset: {len(onsets)}/{len(measured)} ailə sınıb; "
                     f"ən erkən t{min(onsets)}, median t{sorted(onsets)[len(onsets) // 2]}")
    else:
        lines.append(f"failure-onset: heç bir ailə sınmayıb "
                     f"({len(measured)} ölçülmüş ailə, {counts[-1]} növbəyə qədər)")
    lines.append("* = həmin nöqtədə infrastruktur xətası olub, cavab "
                 "qiymətləndirilməyib (nə keçdi, nə sındı)")
    return "\n".join(lines)


def to_payload(curve: Curve) -> dict[str, Any]:
    agg = curve.aggregate()
    return {
        "runs": curve.runs,
        "turn_counts": curve.turn_counts,
        "families": {
            name: {"onset": fam.onset, "measured": fam.measured,
                   "points": {str(n): asdict(p) for n, p in sorted(fam.points.items())}}
            for name, fam in sorted(curve.families.items())
        },
        "aggregate": {str(n): {"pass_rate": r, "graded": g, "families": c}
                      for n, (r, g, c) in agg.items()},
        "drop_vs_first": {str(n): d for n, d in curve.drop_vs_first().items()},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("reports", nargs="+", help="reports/<run_id> qovluğu və ya JSON faylı")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    curve = load(Path(p) for p in args.reports)
    print(render(curve))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(to_payload(curve), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        print(f"\nJSON: {args.json_out}")
    return 0 if curve.families else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

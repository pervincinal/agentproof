#!/usr/bin/env python
"""Bir neçə qaçışı TƏK RunRecord artefaktına birləşdirir (AP-042 / AP-013).

    # yarımçıq qalmış qaçış + onu tamamlayan təkrar qaçış -> baseline
    python evals/merge_runs.py reports/full-run-03 reports/full-run-03b \\
        --merge-across-datasets \\
        --out evals/baselines/dify_http@e60c825c84bbda8a-2026-08-28.json

NİYƏ ƏL İLƏ BİRLƏŞDİRMƏK OLMAZ. Baseline sənədləşmiş və TƏKRAR İSTEHSAL OLUNAN
yolla alınmalıdır: hansı qaçışlardan, hansı qayda ilə. Əl ilə yamanmış JSON
audit sənədi deyil. Bu alət qaydanı kodda saxlayır (`report/merge.py`) və
nəticəyə `totals["merge"]` provenans blokunu yazır — hansı case hansı qaçışdan
gəldi, nə əvəz olundu, hansı xəbərdarlıq var.

Qapı: birləşmədən sonra ölçülməmiş (`skipped`) case qalırsa yazmır. Baseline
"bu case ölçülmədi" saxlaya bilməz — həmin case-lər gələcək reqressiya
yoxlamasından səssizcə kənarda qalardı. `--allow-skipped` bunu bilərəkdən açır.

Çıxış kodu: 0 — yazıldı · 1 — qapı bloklаdı.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentproof.report.cost import summary_line  # noqa: E402
from agentproof.report.merge import merge_records, render_merge_notes  # noqa: E402
from agentproof.report.normalize import read_case_fingerprints  # noqa: E402
from agentproof.types import RunRecord  # noqa: E402


def _record_paths(paths: list[str]) -> list[Path]:
    """Qaçış qovluğu -> içindəki RunRecord JSON-u (hesabat artefaktları xaric)."""
    skip = {"reproduction.json", "pr-comment.json"}
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            found = sorted(q for q in p.glob("*.json") if q.name not in skip)
            if not found:
                raise SystemExit(f"{p}: RunRecord JSON tapılmadı")
            if len(found) > 1:
                raise SystemExit(
                    f"{p}: bir neçə JSON var ({', '.join(q.name for q in found)}) — "
                    "hansının qaçış qeydi olduğunu alət təxmin etmir, faylı birbaşa ver"
                )
            out += found
        elif p.suffix == ".json":
            out.append(p)
        else:
            raise SystemExit(f"naməlum giriş: {p} (.json və ya qaçış qovluğu gözlənilir)")
    if len(out) < 2:
        raise SystemExit("birləşdirmək üçün ən azı iki qaçış lazımdır")
    return out


def _fingerprints(record_path: Path) -> dict[str, str]:
    """Qaçışın `.eval` logundan case TƏRİF barmaq izləri (tapılmasa boş).

    Bu, fərqli `dataset_hash`-lı iki qaçışı birləşdirməyin yeganə obyektiv
    sübutudur: RunRecord case mətnini saxlamır, log saxlayır.
    """
    logs = sorted(record_path.parent.rglob("*.eval"))
    marks: dict[str, str] = {}
    for log in logs:
        marks.update(read_case_fingerprints(str(log)))
    return marks


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="merge-runs", description="Qaçışları birləşdir")
    p.add_argument("paths", nargs="+", help="qaçış qovluqları və ya RunRecord JSON-ları")
    p.add_argument("--out", required=True, help="yazılacaq RunRecord JSON")
    p.add_argument("--merge-across-datasets", action="store_true",
                   help=("əvəzləmə fərqli `dataset_hash`-ları da keçsin (yalnız case "
                         "tərifinin barmaq izi eyni olanda). `--filter` ilə qaçırılan "
                         "təkrar qaçış üçün lazımdır"))
    p.add_argument("--allow-skipped", action="store_true",
                   help="birləşmədən sonra ölçülməmiş case qalsa da yaz (baseline üçün TÖVSİYƏ OLUNMUR)")
    args = p.parse_args(argv)

    paths = _record_paths(args.paths)
    records = [
        RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))) for path in paths
    ]
    prints = [_fingerprints(path) for path in paths]
    verified = all(prints)
    merged, outcome = merge_records(
        records,
        sources=[str(path) for path in paths],
        fingerprints=prints if verified else None,
        allow_cross_dataset=args.merge_across_datasets,
    )

    t = merged.totals
    print(f"Mənbələr ({len(paths)}):")
    for record, path in zip(records, paths):
        print(
            f"  - {record.run_id} · {record.started_at} · dataset {record.dataset_hash} · "
            f"{len(record.results)} nəticə · sxem v{record.schema_version} · {path}"
        )
    print()
    print(
        "Case tərif barmaq izləri: "
        + (
            "`.eval` loglarından oxundu — birləşmə YOXLANILDI"
            if verified
            else "log tapılmadı, YOXLANMADI (RunRecord case mətnini saxlamır)"
        )
    )
    print(f"Birləşmiş qeyd: {merged.run_id} · dataset {merged.dataset_hash}")
    print(
        f"  case {t['n_cases']} · keçdi {t['n_passed']} · sındı {t['n_failed']} · "
        f"skip {t['n_skipped']} · keçmə {t['pass_rate']:.1%}"
    )
    print(f"  {summary_line(t)}")
    notes = render_merge_notes(outcome)
    if notes:
        print()
        print(notes)

    if t["n_skipped"] and not args.allow_skipped:
        print(
            f"\nBLOKLANDI: birləşmədən sonra {t['n_skipped']} case hələ də ölçülməyib "
            "(`skipped`). Baseline ölçülməmiş case saxlaya bilməz — həmin case-lər "
            "reqressiya yoxlamasından səssizcə kənarda qalar. Qalan case-ləri qaçır "
            "və nəticəni bura əlavə et, ya da bilərəkdən `--allow-skipped` ver.",
            file=sys.stderr,
        )
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(merged.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nYazıldı: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

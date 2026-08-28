#!/usr/bin/env python
"""Reproduksiya qapısı — CLI (AP-007, PLAN.md keyfiyyət qaydası #1).

    # əsl mənbə: `.eval` logu (hər cəhd AYRICA qiymətləndirilir)
    python evals/reproduce.py reports/full-run-02

    # və ya birbaşa fayl(lar)
    python evals/reproduce.py reports/full-run-02/logs/*.eval --out repro.json

    # bir neçə müstəqil qaçışın RunRecord-u da olar
    python evals/reproduce.py reports/runs/a.json reports/runs/b.json

    # yarımçıq qalmış qaçış + onu tamamlayan təkrar qaçış (AP-042)
    python evals/reproduce.py reports/full-run-03 reports/full-run-03b \
        --merge-across-datasets

BİRLƏŞMƏ (AP-042). Eyni `case_id` bir neçə qaçışda görünürsə, ƏN SON qaçışın
(`created` / `started_at`) nəticəsi götürülür; əvvəlki SİLİNMİR — `superseded`
kimi sayılır və xülasədə görünür. Beləliklə kredit kəsilməsindən sonra
tamamlanan qaçışda case-lər İKİQAT sayılmır.

  * Qaçışların tarixi eynidirsə (və ya oxunmursa) sıralama yoxdur — nəticələr
    müstəqil CƏHD kimi qalır. `--as-repeats` bunu həmişə məcbur edir.
  * Əvəzləmə eyni `dataset_hash` daxilində baş verir. `--merge-across-datasets`
    sərhədi keçir, AMMA yalnız case tərifinin barmaq izi eyni olduqda.
    (`dataset_hash` filtrdən SONRAKI case dəstinə görə hesablanır, ona görə
    `--filter` ilə qaçırılan təkrar qaçışın hash-i həmişə fərqlidir.)

Çıxış: insan üçün mətn (stdout) + maşın üçün JSON (`--out`, default olaraq
qovluq verilibsə `<qovluq>/reproduction.json`).

Çıxış kodu:
  0 — təsnifat aparıldı
  2 — təsnifat MÜMKÜN DEYİL (təkrar yoxdur / RunRecord təkrarları birləşdirib)
  3 — flaky nisbəti həddi aşdı (`--fail-on-flaky` verilibsə)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentproof.report import reproduction  # noqa: E402
from agentproof.report.merge import render_merge_notes  # noqa: E402
from agentproof.report.normalize import read_repeat_samples  # noqa: E402
from agentproof.types import RunRecord  # noqa: E402


def _expand(paths: list[str]) -> tuple[list[Path], list[Path]]:
    """Verilən yolları `.eval` logları və RunRecord JSON-larına ayırır."""
    logs: list[Path] = []
    records: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            found = sorted(p.rglob("*.eval"))
            if found:
                logs += found
                continue
            records += sorted(q for q in p.glob("*.json") if q.name != "reproduction.json")
            continue
        if p.suffix == ".eval":
            logs.append(p)
        elif p.suffix == ".json":
            records.append(p)
        else:
            raise SystemExit(f"naməlum giriş: {p} (.eval və ya .json gözlənilir)")
    return logs, records


def build(
    paths: list[str],
    *,
    supersede: bool = True,
    allow_cross_dataset: bool = False,
) -> reproduction.ReproductionReport:
    logs, records = _expand(paths)
    if not logs and not records:
        raise SystemExit(f"giriş tapılmadı: {', '.join(paths)}")
    if logs:
        # `.eval` logu üstündür: cəhd-səviyyəli cavablar YALNIZ orada var.
        samples: list = []
        for log in logs:
            origin, pairs = read_repeat_samples(str(log))
            samples += [(meta, responses, origin) for meta, responses in pairs]
        return reproduction.from_log_samples(
            samples,
            source=", ".join(str(p) for p in logs),
            supersede=supersede,
            allow_cross_dataset=allow_cross_dataset,
        )
    loaded = [
        RunRecord.from_dict(json.loads(p.read_text(encoding="utf-8"))) for p in records
    ]
    return reproduction.from_records(
        loaded,
        source=", ".join(str(p) for p in records),
        sources=[str(p) for p in records],
        supersede=supersede,
        allow_cross_dataset=allow_cross_dataset,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="reproduce", description="Reproduksiya qapısı")
    p.add_argument("paths", nargs="+", help="qaçış qovluğu, .eval log(lar)ı və ya RunRecord JSON-ları")
    p.add_argument("--out", default=None, help="JSON çıxış faylı")
    p.add_argument("--fail-on-flaky", action="store_true",
                   help=f"flaky nisbəti {reproduction.FLAKY_ALARM:.0%} keçsə 3 qaytar")
    p.add_argument("--as-repeats", action="store_true",
                   help=("əvəzləməni SÖNDÜR: hər qaçış müstəqil cəhd sayılsın "
                         "(eyni case-i N dəfə qaçırıb reproduksiya ölçmək üçün). "
                         "Default: eyni case_id-nin ƏN SON qaçışı götürülür"))
    p.add_argument("--merge-across-datasets", action="store_true",
                   help=("əvəzləmə fərqli `dataset_hash`-ları da keçsin. YALNIZ case "
                         "tərifinin barmaq izi eyni olduqda birləşdirir; fərqli olan "
                         "case heç vaxt birləşmir. `--filter` ilə qaçırılan təkrar "
                         "qaçış üçün lazımdır (hash filtrdən SONRA hesablanır)"))
    args = p.parse_args(argv)

    report = build(
        args.paths,
        supersede=not args.as_repeats,
        allow_cross_dataset=args.merge_across_datasets,
    )

    out = Path(args.out) if args.out else None
    if out is None:
        first = Path(args.paths[0])
        if first.is_dir():
            out = first / "reproduction.json"
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    print(reproduction.render_text(report))
    if report.superseded:
        print()
        print(
            render_merge_notes(
                reproduction.MergeOutcome(
                    superseded=report.superseded, warnings=[]
                )
            )
        )
    if out is not None:
        print(f"\nJSON: {out}")

    if not report.classifiable:
        print("\nTəsnifat mümkün deyil — FINDINGS.md üçün namizəd yoxdur.", file=sys.stderr)
        return 2
    if args.fail_on_flaky and report.flaky_alarm:
        print(
            f"\nFlaky nisbəti həddi aşdı: {report.flaky_rate:.1%} > "
            f"{reproduction.FLAKY_ALARM:.0%}",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

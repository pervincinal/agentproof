#!/usr/bin/env python
"""CI qapıları — şəbəkəsiz, hər PR-da qaçan bloklayıcı yoxlamalar (AP-011).

    python evals/ci_gates.py calibration --dataset evals/datasets/full.jsonl
    python evals/ci_gates.py artifact    reports/ci-smoke
    python evals/ci_gates.py baseline    evals/baselines

Niyə workflow YAML-ında deyil, burada: YAML-a yazılmış `python - <<'PY'` bloku
nə test olunur, nə lokal təkrarlanır, nə də sındığında oxunaqlı olur. Bu
qapıların hər birinin `agentproof/tests/test_ci_gates.py`-də bilərəkdən keçən
və bilərəkdən sınan nümunəsi var.

Çıxış kodu: 0 — qapı keçdi · 1 — BLOKLANDI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentproof.graders import registry  # noqa: E402
from agentproof.graders.calibration import (  # noqa: E402
    MIN_AGREEMENT,
    MIN_KAPPA,
    CalibrationReport,
    load_report,
)
from agentproof.types import RunRecord  # noqa: E402

BASELINE_MISSING = (
    "BASELINE YOXDUR — REQRESSİYA YOXLANILMADI.\n"
    "`{path}` boşdur, ona görə bu qaçışda yalnız MÜTLƏQ rəqəmlər var: hansı\n"
    "case-in SINDIĞI bilinmir. Yaşıl status «reqressiya yoxdur» demək DEYİL —\n"
    "snapshot olmadan reqressiya qapısı BAĞLIDIR.\n"
    "Snapshot AP-013-də götürülüb; qovluq boşdursa fayl itib və ya silinib.\n"
    "Yenidən götürmək: docs/BASELINE.md"
)


def _emit_summary(text: str) -> None:
    """GitHub job xülasəsinə yazır (dəyişən yoxdursa səssizcə keçir)."""
    import os

    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n\n")


# ---------------------------------------------------------- kalibrasiya qapısı
def judge_graders_in(dataset: Path) -> list[str]:
    """Dataset-də HƏQİQƏTƏN işlədilən judge grader-lərinin adları."""
    names: set[str] = set()
    for line in dataset.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            grader = json.loads(line).get("grader", "")
        except ValueError:
            continue
        if grader in registry.names() and registry.kind(grader) == "judge":
            names.add(grader)
    return sorted(names)


def calibration_verdict(
    judged: list[str], report: CalibrationReport | None
) -> tuple[bool, str]:
    """`(keçdi, mesaj)`.

    Judge grader-i yoxdursa qapı tətbiq olunmur. Varsa — kalibrasiya hesabatının
    OLMAMASI da bloklayır: kalibrasiya edilməmiş judge nəticəsi elmi zibildir
    (grader-eng.md), ona görə «hesabat yoxdur» halı susmaqla keçmir.
    """
    if not judged:
        return True, "Dataset-də judge grader-i yoxdur — kalibrasiya tələb olunmur."
    head = f"Judge grader-ləri: {', '.join(judged)}"
    if report is None:
        return False, (
            f"{head}\nKALİBRASİYA HESABATI YOXDUR — `evals/calibration/report.json` "
            "commit edilməyib.\n  Qaçır: python evals/calibration/run_calibration.py"
        )
    if report.dry_run:
        return False, (
            f"{head}\n{report.summary_line()}\nDRY-RUN kalibrasiyası (sabit verdikt "
            "verən null model) qiymətləndirmə kimi qəbul edilmir."
        )
    if report.blocking_reasons:
        return False, (
            f"{head}\n{report.summary_line()}\n"
            f"Kalibrasiya qapısı BLOKLADI (hədd: uyğunluq ≥ {MIN_AGREEMENT:.0%}, "
            f"κ ≥ {MIN_KAPPA:.2f}):\n  - " + "\n  - ".join(report.blocking_reasons)
        )
    return True, f"{head}\n{report.summary_line()}"


def cmd_calibration(args: argparse.Namespace) -> int:
    judged = judge_graders_in(Path(args.dataset))
    passed, message = calibration_verdict(judged, load_report())
    print(message, file=sys.stdout if passed else sys.stderr)
    return 0 if passed else 1


# -------------------------------------------------------------- artefakt qapısı
def artifact_problems(record: RunRecord) -> list[str]:
    """Duman testinin RunRecord-u bütövdürmü.

    Boru xətti «qaçdı və 0 qaytardı» ilə «doğru ölçdü» eyni şey deyil: qaçış
    boş dataset, itmiş provenans və ya səbəbsiz uğursuzluqla da yaşıl bitə
    bilər. Bu qapı məhz həmin səssiz halları tutur.
    """
    problems: list[str] = []
    if not record.results:
        problems.append("case nəticəsi yoxdur — dataset yüklənmədi və ya filtr hamısını atdı")
    if not record.dataset_hash:
        problems.append("dataset_hash boşdur — provenans itib")
    n_cases = record.totals.get("n_cases")
    if n_cases is not None and n_cases != len(record.results):
        problems.append(f"totals.n_cases={n_cases}, nəticə sayı={len(record.results)}")
    # STACK.md §8.3 müqavilə şərti: passed=False üçün boş `reason` qəbul olunmur.
    silent = [
        r.case_id
        for r in record.results
        if not r.grade.passed and not r.grade.skipped and not r.grade.reason
    ]
    if silent:
        problems.append(f"səbəbsiz uğursuzluq ({len(silent)}): {silent[:5]}")
    ungraded = [r.case_id for r in record.results if not r.grade.grader]
    if ungraded:
        problems.append(f"grader adı yazılmayıb ({len(ungraded)}): {ungraded[:5]}")
    # AP-024: yarımçıq dayandırılmış qaçış YAŞIL çıxa bilməz — qalan case-lər
    # hədəfə ümumiyyətlə göndərilmədi, yəni ölçülmədi.
    halted = record.totals.get("halted") or {}
    if halted.get("halted"):
        problems.append(
            f"qaçış yarıda dayandırıldı ({halted.get('reason', '?')}) — "
            f"ilk görünmə: {halted.get('case_id') or '?'}; nəticə TAM DEYİL"
        )
    return problems


def cmd_artifact(args: argparse.Namespace) -> int:
    run = Path(args.run)
    paths = (
        sorted(p for p in run.glob("*.json") if p.name != "reproduction.json")
        if run.is_dir()
        else [run]
    )
    if not paths or not paths[0].exists():
        print(f"RunRecord yazılmadı: {run} — boru xətti sındı.", file=sys.stderr)
        return 1
    record = RunRecord.from_dict(json.loads(paths[0].read_text(encoding="utf-8")))
    problems = artifact_problems(record)
    if problems:
        print("Duman testi artefaktı qüsurlu:\n  - " + "\n  - ".join(problems), file=sys.stderr)
        return 1
    t = record.totals
    print(
        f"RunRecord OK · {len(record.results)} case · dataset {record.dataset_hash} · "
        f"{t.get('n_failed', 0)} sındı · {t.get('n_skipped', 0)} skip"
    )
    return 0


# -------------------------------------------------------------- baseline qapısı
def _newest_baseline(files: list[Path]) -> Path:
    """Ən son ÖLÇÜLMÜŞ baseline — `started_at`-a görə, fayl adına görə YOX.

    AP-042 ilə eyni qayda: sıralama meyarı zamandır. Fayl adı sıralaması
    "…-2026-09-01" ilə "…-2026-10-01"-i düzgün sıralasa da, ad sxemi
    dəyişən kimi səssizcə yanlış snapshot seçərdi. Oxuna bilməyən fayl
    (bozuk JSON) sondan yox, əvvəldən sayılır — o, seçilməməlidir.
    """

    def moment(path: Path) -> tuple[int, str, str]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            stamp = str(data.get("started_at") or "")
        except (ValueError, OSError):
            return (0, "", path.name)
        return (1 if stamp else 0, stamp, path.name)

    return sorted(files, key=moment)[-1]


def cmd_baseline(args: argparse.Namespace) -> int:
    """Baseline YOXDURSA SƏSSİZ KEÇMİR — açıq şəkildə etiraf olunur.

    Qapı özü default olaraq qırmızı yandırmır, amma həm konsola, həm job
    xülasəsinə yazır ki, yaşıl CI «reqressiya yoxdur» kimi oxunmasın.
    `--require` verilibsə bloklayır — AP-013-dən sonra CI məhz belə qaçır.

    Bir neçə snapshot varsa ƏN SONUNCUSU seçilir: meyar `started_at`, fayl adı
    yox (AP-042 ilə eyni qayda).

    STDOUT yalnız tapılan baseline yoludur (yoxdursa boş sətir) — workflow onu
    birbaşa oxuyur. Bütün insan mətni stderr-ə gedir ki, yol qarışmasın.
    """
    directory = Path(args.directory)
    files = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if files:
        chosen = _newest_baseline(files)
        listing = ", ".join(f.name for f in files)
        print(
            f"Baseline snapshot-ları: {listing}\nSeçildi: {chosen.name}", file=sys.stderr
        )
        _emit_summary(
            f"**Baseline:** `{chosen.name}` — reqressiya qapısı aktiv."
            + (f" (qovluqda {len(files)} snapshot var)" if len(files) > 1 else "")
        )
        print(chosen)
        return 0

    message = BASELINE_MISSING.format(path=directory)
    print(message, file=sys.stderr)
    _emit_summary("### ⚠️ Baseline yoxdur — REQRESSİYA YOXLANILMADI\n\n```\n" + message + "\n```")
    print("")  # boş yol: `--baseline` bayrağı ötürülmür
    return 1 if args.require else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ci-gates", description="AgentProof CI qapıları")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("calibration", help="judge kalibrasiya həddi (şəbəkəsiz)")
    c.add_argument("--dataset", default="evals/datasets/full.jsonl")
    c.set_defaults(func=cmd_calibration)

    a = sub.add_parser("artifact", help="duman testinin RunRecord-u bütövdürmü")
    a.add_argument("run", help="qaçış qovluğu və ya RunRecord JSON")
    a.set_defaults(func=cmd_artifact)

    b = sub.add_parser("baseline", help="baseline snapshot-u varmı")
    b.add_argument("directory", nargs="?", default="evals/baselines")
    b.add_argument("--require", action="store_true", help="yoxdursa bloklа (exit 1)")
    b.set_defaults(func=cmd_baseline)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Judge kalibrasiya qaçışı.

    # şəbəkəsiz — boru xəttini yoxlayır, "null model" bazasını göstərir
    python evals/calibration/run_calibration.py --dry-run

    # real qaçış (ANTHROPIC_API_KEY və ya `ant auth login` profili lazımdır)
    python evals/calibration/run_calibration.py --model claude-opus-5

Çıxış: `evals/calibration/report.json` + konsol xülasəsi.
Həmin fayl `report/normalize.py` və `report/pr_comment.py` tərəfindən avtomatik
oxunur — yəni uyğunluq faizi və kappa hər eval hesabatında görünür və
gizlədilə bilmir.

QAYDA: uyğunluq 85%-dən aşağıdırsa RUBRİKA (`agentproof/graders/judge.py`)
düzəldilir, `labeled.yaml` DEYİL. Səbəb: `agentproof/graders/calibration.py`
modul sənədində.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentproof.graders.calibration import (  # noqa: E402
    DEFAULT_LABELS_PATH,
    DEFAULT_REPORT_PATH,
    ConstantJudgeClient,
    calibrate,
    load_labels,
    save_report,
)
from agentproof.graders.judge import (  # noqa: E402
    DEFAULT_JUDGE_MODEL,
    AnthropicJudgeClient,
    JudgeConfig,
    RubricJudge,
    supports_temperature,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="calibrate", description="Judge kalibrasiyası")
    p.add_argument("--labels", default=str(DEFAULT_LABELS_PATH))
    p.add_argument("--out", default=str(DEFAULT_REPORT_PATH))
    p.add_argument("--model", default=DEFAULT_JUDGE_MODEL, help="judge modeli")
    p.add_argument("--sut-model", default=None,
                   help="qiymətləndirilən sistemin modeli — judge ondan güclü olmalıdır")
    p.add_argument("--cache-dir", default=None,
                   help="cavab keşi (determinizm: eyni prompt → eyni verdikt)")
    p.add_argument("--dry-run", action="store_true",
                   help="şəbəkəsiz sabit-verdiktli null model; nəticə bloklanır")
    p.add_argument("--dry-run-verdict", default="unjustified")
    p.add_argument("--fail-under-threshold", action="store_true",
                   help="CI: hədd keçilmirsə exit 1")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dataset = load_labels(args.labels)

    print(f"Kalibrasiya dəsti : {dataset.path}")
    print(f"  nümunə          : {len(dataset)}")
    print(f"  rubrika         : {dataset.rubric}@{dataset.rubric_version}")
    print(f"  sinif balansı   : " + ", ".join(f"{k}={v}" for k, v in sorted(dataset.label_counts.items())))
    print(f"  sha256          : {dataset.sha256[:16]}")
    print()

    if args.dry_run:
        client = ConstantJudgeClient(args.dry_run_verdict)
        judge = RubricJudge()
        print(f"DRY-RUN · null model (həmişə '{args.dry_run_verdict}') · şəbəkə çağırışı YOXDUR")
    else:
        config = JudgeConfig(
            model=args.model,
            cache_dir=args.cache_dir,
            sut_model=args.sut_model,
        )
        config.validate()
        client = AnthropicJudgeClient(model=args.model, temperature=config.temperature)
        judge = RubricJudge(config=config)
        applied = supports_temperature(args.model)
        print(f"Judge modeli      : {args.model}")
        print(
            "  temperature     : "
            + ("0 (tətbiq olunur)" if applied else
               "GÖNDƏRİLMİR — bu model sampling parametrlərini rədd edir (HTTP 400); "
               "determinizm prompt sabitliyi + keş ilə təmin olunur")
        )

    report = calibrate(
        client,
        dataset,
        judge=judge,
        dry_run=args.dry_run,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    path = save_report(report, args.out)

    print()
    print(report.summary_line())
    print()
    print(report.render_markdown())
    print(f"Hesabat: {path}")

    if report.blocking_reasons:
        print("\nBloklama səbəbləri:", file=sys.stderr)
        for reason in report.blocking_reasons:
            print(f"  - {reason}", file=sys.stderr)
        if args.fail_under_threshold:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

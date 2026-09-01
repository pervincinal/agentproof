#!/usr/bin/env python
"""CI xülasəsi — job summary və PR şərhi üçün markdown (AP-011).

    python evals/ci_summary.py reports/ci-smoke --out pr-comment.md
    python evals/ci_summary.py reports/ci-smoke --baseline evals/baselines/x.json

Niyə ayrıca fayl: workflow YAML-ında yazılmış skript nə test olunur, nə də
lokal təkrarlana bilir. Burada isə eyni mətn `pytest` ilə yoxlanır və mühəndis
CI-a push etmədən əvvəl eyni əmri qaçıra bilir.

**Baseline yoxdursa SƏSSİZ KEÇMİR.** `report/pr_comment.py` mütləq rəqəm deyil,
DƏYİŞİKLİK göstərmək üçün yazılıb; baseline olmayanda göstəriləcək dəyişiklik
yoxdur. Bu halda «68% keçdi» yazıb dayanmaq auditdə «reqressiya yoxdur» kimi
oxunur. Ona görə şərh açıq banner ilə başlayır: REQRESSİYA YOXLANILMADI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentproof.report.baseline import GatePolicy, compare, gate  # noqa: E402
from agentproof.report.pr_comment import judge_block, render, render_console  # noqa: E402
from agentproof.types import RunRecord  # noqa: E402

NO_BASELINE_BANNER = (
    "> ⚠️ **BASELINE YOXDUR — REQRESSİYA YOXLANILMADI.**\n"
    "> Aşağıdakı rəqəmlər MÜTLƏQ dəyərlərdir. Bu qaçışda hansı case-in SINDIĞI\n"
    "> bilinmir, çünki müqayisə üçün snapshot yoxdur (`evals/baselines/` boşdur).\n"
    "> «Reqressiya görünmür» ilə «reqressiya yoxdur» eyni şey deyil — AP-013."
)


def find_record(path: Path) -> Path:
    """Qaçış qovluğundan RunRecord JSON-u tapır (reproduction.json istisna)."""
    if path.is_file():
        return path
    candidates = sorted(p for p in path.glob("*.json") if p.name != "reproduction.json")
    if not candidates:
        raise SystemExit(f"RunRecord tapılmadı: {path}")
    return candidates[0]


def load(path: Path) -> RunRecord:
    return RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def build(
    record: RunRecord,
    baseline: RunRecord | None,
    title: str,
    max_pass_rate_drop: float = 0.02,
    fail_on_repeat_mismatch: bool = False,
) -> tuple[str, bool]:
    """`(markdown, qapı keçdi)` qaytarır.

    Baseline yoxdursa qapı «keçdi» sayılır — bloklamaq üçün müqayisə lazımdır —
    amma mətn bunu gizlətmir.
    """
    if baseline is not None:
        delta = compare(record, baseline)
        result = gate(
            delta,
            GatePolicy(
                max_pass_rate_drop=max_pass_rate_drop,
                fail_on_repeat_mismatch=fail_on_repeat_mismatch,
            ),
        )
        return f"## {title}\n\n" + render(delta, record, result), result.passed

    body = [
        f"## {title}",
        "",
        NO_BASELINE_BANNER,
        "",
        "```",
        render_console(record),
        "```",
        "",
    ]
    # Judge kalibrasiyası baseline-dan ASILI DEYİL: judge işlədilibsə bölmə
    # burada da məcburidir (pr_comment.judge_block eyni məntiqi verir).
    body += judge_block(record)
    return "\n".join(body), True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ci-summary", description="CI markdown xülasəsi")
    p.add_argument("run", help="qaçış qovluğu və ya RunRecord JSON")
    p.add_argument("--baseline", default=None, help="baseline RunRecord JSON")
    p.add_argument("--out", default=None, help="markdown çıxış faylı")
    p.add_argument("--title", default="AgentProof eval")
    p.add_argument("--max-pass-rate-drop", type=float, default=0.02)
    p.add_argument("--fail-on-regression", action="store_true")
    p.add_argument("--fail-on-repeat-mismatch", action="store_true",
                   help=("qaçış baseline-dan AZ `--repeat` ilə ölçülübsə blokla "
                         "(AP-043). Verilməsə yalnız xəbərdarlıq göstərilir"))
    args = p.parse_args(argv)

    record = load(find_record(Path(args.run)))

    baseline = None
    if args.baseline:
        base_path = Path(args.baseline)
        if base_path.exists():
            baseline = load(base_path)
        else:
            print(
                f"Baseline tapılmadı: {base_path} — REQRESSİYA YOXLANILMADI.",
                file=sys.stderr,
            )

    markdown, passed = build(
        record, baseline, args.title, args.max_pass_rate_drop,
        fail_on_repeat_mismatch=args.fail_on_repeat_mismatch,
    )
    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
    print(markdown)

    if args.fail_on_regression and not passed:
        print("\nREQRESSİYA — CI bloklandı.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

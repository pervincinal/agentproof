#!/usr/bin/env python
"""AgentProof — tək giriş nöqtəsi (STACK.md §8.6).

    python evals/run.py --target mock --dataset evals/datasets/spike.jsonl

Paralellik, retry və rate-limit Inspect-dən gəlir (`--max-connections`).
Adapter konfiqurasiyası mühit dəyişənlərindən oxunur — açar heç vaxt CLI-a
və ya loga düşmür.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inspect_ai import eval as inspect_eval  # noqa: E402

from agentproof.report.baseline import GatePolicy, compare, gate  # noqa: E402
from agentproof.report.normalize import normalize_log  # noqa: E402
from agentproof.report.pr_comment import render, render_console  # noqa: E402
from agentproof.runner.task import build_task, select_cases  # noqa: E402
from agentproof.types import RunRecord  # noqa: E402

DEFAULT_DATASET = "evals/datasets/spike.jsonl"


def adapter_config_from_env(target: str) -> dict[str, object]:
    """Açarlar YALNIZ mühitdən. CI-da secret-dən gəlir, loga düşmür."""
    if target != "dify_http":
        return {}
    config: dict[str, object] = {}
    if os.environ.get("DIFY_BASE_URL"):
        config["base_url"] = os.environ["DIFY_BASE_URL"]
    if os.environ.get("DIFY_API_KEY"):
        config["api_key"] = os.environ["DIFY_API_KEY"]
    if os.environ.get("DIFY_APP_VERSION"):
        config["version"] = os.environ["DIFY_APP_VERSION"]
    return config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="agentproof", description="AgentProof eval qaçışı")
    p.add_argument("--target", required=True, help="adapter adı (mock | dify_http)")
    p.add_argument("--dataset", default=DEFAULT_DATASET)
    p.add_argument("--filter", dest="filter_expr", default=None,
                   help="tag=policy,severity=high (açarlar: tag|severity|grader|id)")
    p.add_argument("--stage", default="all", choices=["cheap", "judge", "all"])
    p.add_argument("--repeat", type=int, default=1,
                   help="qeyri-determinist case-lər üçün N müstəqil cavab")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--baseline", default=None)
    p.add_argument("--max-connections", type=int, default=8)
    p.add_argument("--out", default=None, help="reports/<run_id>/ qovluğu")
    p.add_argument("--fail-on-regression", action="store_true")
    p.add_argument("--max-pass-rate-drop", type=float, default=0.02)
    p.add_argument("--target-version", default=os.environ.get("AGENTPROOF_TARGET_VERSION", ""))
    p.add_argument("--model", default=os.environ.get("AGENTPROOF_SUT_MODEL", ""),
                   help="hədəfin İÇİNDƏKİ model (yalnız hesabat üçün etiket)")
    p.add_argument("--log-dir", default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not select_cases(args.dataset, args.filter_expr, args.stage):
        print("Filtrə uyğun case yoxdur — qaçış dayandırıldı.", file=sys.stderr)
        return 2

    task, _cases = build_task(
        dataset_path=args.dataset,
        adapter=args.target,
        adapter_config=adapter_config_from_env(args.target),
        filter_expr=args.filter_expr,
        stage=args.stage,
        repeat=args.repeat,
        seed=args.seed,
    )

    out_dir = Path(args.out) if args.out else Path("reports") / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = args.log_dir or str(out_dir / "logs")

    logs = inspect_eval(
        task,
        # Hədəf MODEL deyil, MƏHSULDUR — Inspect model qatı ümumiyyətlə işə düşmür.
        # Nəticə: API açarı olmadan da qaçır (R1 spike, yol b).
        model=None,
        log_dir=log_dir,
        max_connections=args.max_connections,
        max_samples=args.max_connections,
        display="plain",
        log_level="warning",
    )
    log = logs[0]
    if log.status != "success":
        print(f"Qaçış uğursuz: {log.status} — {getattr(log, 'error', None)}", file=sys.stderr)
        return 1

    record = normalize_log(
        log, target=args.target, target_version=args.target_version, model=args.model
    )
    record_path = out_dir / f"{record.run_id}.json"
    record_path.write_text(
        json.dumps(record.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    delta = None
    gate_result = None
    if args.baseline:
        baseline_path = Path(args.baseline)
        if not baseline_path.exists():
            print(f"Baseline tapılmadı: {baseline_path} — müqayisə atlanır.", file=sys.stderr)
        else:
            baseline = RunRecord.from_dict(json.loads(baseline_path.read_text()))
            delta = compare(record, baseline)
            gate_result = gate(delta, GatePolicy(max_pass_rate_drop=args.max_pass_rate_drop))
            (out_dir / f"{record.run_id}.pr.md").write_text(
                render(delta, record, gate_result), encoding="utf-8"
            )

    print()
    print(render_console(record, delta))
    print(f"\nRunRecord: {record_path}")

    if args.fail_on_regression and gate_result is not None and not gate_result.passed:
        print("\nREQRESSIYA — CI bloklandı:", file=sys.stderr)
        for reason in gate_result.reasons:
            print(f"  - {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

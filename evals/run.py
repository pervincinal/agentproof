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

from agentproof.graders import registry  # noqa: E402
from agentproof.graders.calibration import load_report  # noqa: E402
from agentproof.graders.judge import (  # noqa: E402
    DEFAULT_JUDGE_MODEL,
    AnthropicJudgeClient,
    JudgeConfig,
)
from agentproof.report.baseline import GatePolicy, compare, gate  # noqa: E402
from agentproof.report.normalize import normalize_log  # noqa: E402
from agentproof.report.pr_comment import render, render_console  # noqa: E402
from agentproof.runner.isolation import build_lane_pool  # noqa: E402
from agentproof.runner.retrieval_config import (  # noqa: E402
    RetrievalCheck,
    apply_retrieval,
    probe_retrieval_config,
)
from agentproof.runner.sut_model import (  # noqa: E402
    ModelCheck,
    SutModelMismatch,
    verify_sut_model,
)
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


def load_lanes(spec: str) -> list[dict[str, object]] | None:
    """`--lanes` ya JSON fayl yoludur, ya birbaşa JSON sətri."""
    spec = (spec or "").strip()
    if not spec:
        return None
    text = Path(spec).read_text(encoding="utf-8") if not spec.startswith("[") else spec
    lanes = json.loads(text)
    if not isinstance(lanes, list) or not lanes:
        raise ValueError("--lanes: boş olmayan JSON siyahısı gözlənilir")
    return lanes


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
                   help=("hədəfin İÇİNDƏKİ model. ETİKETDİR — Dify usage-da model adı "
                         "gəlmir. `--dify-app-id` ilə birlikdə AVTORİTET mənbədən "
                         "(Dify bazası) yoxlanılır"))
    p.add_argument("--dify-app-id",
                   default=os.environ.get("AGENTPROOF_DIFY_APP_ID", ""),
                   help=("modelin yoxlanacağı Dify app id-si. Verilməsə `--model` "
                         "yoxlanılmamış əl etiketi olaraq qalır və hesabatda belə "
                         "işarələnir"))
    p.add_argument("--skip-model-check", action="store_true",
                   help="model yoxlamasını bilərəkdən keç (səbəbi hesabata düşür)")
    p.add_argument("--dataset-id",
                   default=os.environ.get("AGENTPROOF_DATASET_ID", ""),
                   help=("Dify knowledge base id — retrieval konfiqurasiyası bundan "
                         "CANLI oxunur. `--dify-app-id` verilibsə app-ın ÖZ bağlı "
                         "dataset-i üstün tutulur (env bayat ola bilər)"))
    p.add_argument("--dataset-api-key",
                   default=os.environ.get("AGENTPROOF_DATASET_KEY", ""),
                   help=("Dify Knowledge API açarı (`dataset-...`). Verilməsə "
                         "retrieval konfiqurasiyası `unknown` qalır — səssiz "
                         "default verilmir"))
    p.add_argument("--skip-retrieval-check", action="store_true",
                   help=("embedder / `top_k` oxumasını bilərəkdən keç. Səbəb hesabata "
                         "düşür: konfiqurasiyasız qaçış yenidən yoxlana bilmir (LIM-E06)"))
    p.add_argument("--log-dir", default=None)
    p.add_argument(
        "--tool-reset-url",
        default=os.environ.get("AGENTPROOF_TOOL_RESET_URL", ""),
        help=(
            "hədəfin tool servisinin POST /admin/reset ünvanı. Verilməsə İZOLYASİYA "
            "YOXDUR: case n-in yaratdığı RMA case n+1-ə sızır (PLAN.md). "
            "Verilirsə case-lər ATOMİK olur, yəni qaçış seriallaşır."
        ),
    )
    p.add_argument(
        "--lanes",
        default=os.environ.get("AGENTPROOF_LANES", ""),
        help=(
            "paralel lane konfiqurasiyası: JSON fayl yolu və ya sətir. Hər lane "
            "öz tool ad sahəsini (`tool_session` -> X-AG-Session) və öz hədəf "
            "konfiqurasiyasını (`adapter`) alır. N lane = N paralel case, "
            "izolyasiya pozulmadan. Verilməsə tək lane (seriallaşmış) qaçır."
        ),
    )
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL,
                   help="LLM-as-judge modeli — SUT-dan güclü olmalıdır")
    p.add_argument("--judge-cache-dir", default=None,
                   help="judge cavab keşi (determinizm: eyni prompt → eyni verdikt)")
    p.add_argument("--allow-uncalibrated-judge", action="store_true",
                   help="kalibrasiya olmadan judge qaçır (nəticə müdafiə olunmur)")
    return p.parse_args(argv)


def bind_judges(cases, args) -> list[str]:
    """Judge grader-lərinə real klient bağlayır və kalibrasiyanı yoxlayır.

    Kalibrasiya edilməmiş judge nəticəsi elmi zibildir — ona görə qaçış
    default olaraq DAYANIR, susmur (grader-eng.md).
    """
    judged = sorted({c.grader for c in cases if registry.kind(c.grader) == "judge"})
    if not judged:
        return []

    report = load_report()
    if (report is None or not report.passed) and not args.allow_uncalibrated_judge:
        detail = "kalibrasiya hesabatı yoxdur" if report is None else "; ".join(
            report.blocking_reasons
        )
        raise SystemExit(
            f"Judge grader-ləri ({', '.join(judged)}) kalibrasiyasızdır: {detail}\n"
            "  Qaçır: python evals/calibration/run_calibration.py\n"
            "  Bilərəkdən davam etmək üçün: --allow-uncalibrated-judge"
        )

    config = JudgeConfig(
        model=args.judge_model,
        cache_dir=args.judge_cache_dir,
        sut_model=args.model or None,
    )
    config.validate()
    client = AnthropicJudgeClient(model=config.model, temperature=config.temperature)
    for name in judged:
        registry.get(name).bind(client, config)  # type: ignore[union-attr]
    return judged


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    selected = select_cases(args.dataset, args.filter_expr, args.stage)
    if not selected:
        print("Filtrə uyğun case yoxdur — qaçış dayandırıldı.", file=sys.stderr)
        return 2

    for name in bind_judges(selected, args):
        print(f"Judge bağlandı: {name} · model {args.judge_model}", file=sys.stderr)

    # --- `usage.model` AVTORİTET mənbədən yoxlanır ------------------------
    # Uyğunsuzluqda burada dayanırıq: yanlış modelə yazılmış xərc, xərcin
    # ümumiyyətlə olmamasından pisdir, çünki hesabat inandırıcı görünür.
    if args.skip_model_check:
        model_check = ModelCheck(
            status="skipped", declared=args.model, actual="",
            detail="--skip-model-check ilə bilərəkdən keçilib",
        )
    else:
        try:
            model_check = verify_sut_model(args.model, args.dify_app_id or None)
        except SutModelMismatch as e:
            print(f"\n{e}", file=sys.stderr)
            return 1
    if model_check.status == "match":
        print(f"Model yoxlandı: {model_check.actual} (Dify app konfiqurasiyası)", file=sys.stderr)
    elif model_check.status == "adopted":
        print(f"Model app-dən götürüldü: {model_check.actual}", file=sys.stderr)
    else:
        print(f"XƏBƏRDARLIQ — model yoxlanmadı: {model_check.detail}", file=sys.stderr)
    sut_model = model_check.model

    # --- retrieval konfiqurasiyası CANLI sistemdən (LIM-E06 / AP-019) -----
    # Sənəddən, DSL-dən və ya konfiq faylından OXUNMUR — məhz onların
    # ziddiyyəti (DSL `top_k: 4` ↔ faktiki 8) bu addımı doğurdu. Oxuna
    # bilməsə qaçış DAYANMIR, amma dəyər `unknown` qalır və hesabatda
    # xəbərdarlıq görünür.
    if args.skip_retrieval_check:
        retrieval = RetrievalCheck(
            status="skipped",
            detail="--skip-retrieval-check ilə bilərəkdən keçilib",
            warnings=[
                "retrieval konfiqurasiyası bilərəkdən oxunmadı — embedder və "
                "`top_k` `unknown` qalır (LIM-E06)"
            ],
        )
    else:
        retrieval = probe_retrieval_config(
            app_id=args.dify_app_id or None,
            dataset_id=args.dataset_id or None,
            base_url=os.environ.get("DIFY_BASE_URL", ""),
            api_key=args.dataset_api_key,
        )
    if retrieval.ok:
        print(
            f"Retrieval oxundu: {retrieval.embedding_model} "
            f"({retrieval.embedding_provider}) · top_k {retrieval.effective_top_k} · "
            f"dataset {retrieval.dataset_id} [{retrieval.dataset_source}]",
            file=sys.stderr,
        )
    else:
        print(
            f"XƏBƏRDARLIQ — retrieval konfiqurasiyası tam oxunmadı "
            f"({retrieval.status}): {retrieval.detail or '—'}",
            file=sys.stderr,
        )
    for warning in retrieval.warnings:
        print(f"  ⚠️ {warning}", file=sys.stderr)

    lanes = load_lanes(args.lanes)
    pool = build_lane_pool(lanes, args.tool_reset_url or None)

    adapter_config = adapter_config_from_env(args.target)
    if sut_model and args.target == "dify_http":
        # Etiket adapterə də ötürülür ki, `usage.model` mühit dəyişəni ilə
        # yoxlanılmış dəyər arasında ayrılmasın.
        adapter_config["model"] = sut_model

    task, _cases = build_task(
        dataset_path=args.dataset,
        adapter=args.target,
        adapter_config=adapter_config,
        filter_expr=args.filter_expr,
        stage=args.stage,
        repeat=args.repeat,
        seed=args.seed,
        lanes=pool,
    )

    if pool.isolated:
        sessions = ", ".join(f"{ln.name}:{ln.session or '(default)'}" for ln in pool.lanes)
        print(
            f"İzolyasiya AKTİV · {pool.size} lane [{sessions}] — "
            + ("case-lər seriallaşır (tək lane)." if pool.size == 1
               else f"{pool.size} case paralel, hər biri öz tool ad sahəsində."),
            file=sys.stderr,
        )
    else:
        print(
            "İzolyasiya YOXDUR (--tool-reset-url / --lanes verilməyib) — stateful "
            "tool-lu dataset-də nəticələr bir-birinə sıza bilər.",
            file=sys.stderr,
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
        # Paralellik həddi lane sayıdır: hovuz onsuz da bloklayır, amma
        # Inspect-in öz həddi daha kiçik olsa lane-lər boş qalardı.
        max_connections=max(args.max_connections, pool.size),
        max_samples=max(args.max_connections, pool.size),
        display="plain",
        log_level="warning",
    )
    log = logs[0]
    if log.status != "success":
        print(f"Qaçış uğursuz: {log.status} — {getattr(log, 'error', None)}", file=sys.stderr)
        return 1

    record = normalize_log(
        log, target=args.target, target_version=args.target_version, model=sut_model
    )
    # Model yoxlamasının NƏTİCƏSİ hesabata düşür — "yoxlanmadı" halı gizlənə bilməz.
    record.totals["model_check"] = model_check.to_dict()
    record.totals["lanes"] = pool.size
    # Konfiqurasiya artefaktın İÇİNƏ yazılır — kənar sənədə güvənmək məhz
    # LIM-E06-nın səbəbi idi.
    apply_retrieval(record, retrieval)
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

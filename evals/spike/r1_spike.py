"""R1 spike — Inspect-i HTTP arxasındakı RAG agent-inə iki yolla bağlamaq.

Hər iki yol EYNİ 5 case, EYNİ mock Dify serveri və EYNİ grader-lərlə qaçır.
API açarı lazım deyil: hədəf `agentproof.testing.mock_dify` stub-udur.

    .venv/bin/python evals/spike/r1_spike.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from inspect_ai import Task, eval as inspect_eval  # noqa: E402
from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402
from inspect_ai.model import get_model  # noqa: E402
from inspect_ai.solver import generate  # noqa: E402

from agentproof.runner.agent import target_agent  # noqa: E402
from agentproof.runner.scorer import agentproof_scorer  # noqa: E402
from agentproof.runner.task import load_cases  # noqa: E402
from agentproof.testing.mock_dify import MockDifyServer, aurora_fixture  # noqa: E402

DATASET = Path(__file__).resolve().parents[1] / "datasets" / "spike.jsonl"


def _samples() -> tuple[list[Sample], list[Any]]:
    cases = load_cases(DATASET)
    return [Sample(input=c.query, id=c.id, target="", metadata=c.to_dict()) for c in cases], cases


def _summarize(label: str, logs: list[Any]) -> dict[str, Any]:
    log = logs[0]
    out: dict[str, Any] = {"path": label, "status": log.status, "cases": []}
    if log.status != "success":
        out["error"] = str(getattr(log, "error", None))
        return out
    for sample in log.samples or []:
        score = next(iter(sample.scores.values())) if sample.scores else None
        out["cases"].append(
            {
                "id": sample.id,
                "value": None if score is None else score.value,
                "grader": None if score is None else (score.metadata or {}).get("grader"),
                "explanation": None if score is None else score.explanation,
            }
        )
    out["n_pass"] = sum(1 for c in out["cases"] if c["value"] == 1.0)
    out["n_total"] = len(out["cases"])
    return out


def run_path_a(base_url: str, api_key: str, log_dir: str) -> dict[str, Any]:
    """YOL (a): adapter -> Inspect ModelAPI provayderi -> generate() solver."""
    import agentproof.runner.provider  # noqa: F401  (modelapi qeydiyyatı)

    samples, _ = _samples()
    task = Task(
        dataset=MemoryDataset(samples, name="spike-a"),
        solver=generate(),
        scorer=agentproof_scorer(),
        name="r1_spike_modelapi",
    )
    model = get_model(
        "agentproof/dify_http",
        base_url=base_url,
        api_key=api_key,
        fetch_tool_traces=True,
    )
    # ⚠️ `message_limit` OLMADAN bu qaçış BİTMİR: `generate()` solver-i hədəfin
    # tool İZİNİ tool SORĞUSU kimi oxuyur və döngəyə düşür. Bax `docs/R1-SPIKE.md`.
    logs = inspect_eval(
        task,
        model=model,
        log_dir=log_dir,
        display="none",
        log_level="error",
        message_limit=12,
        fail_on_error=False,
    )
    return _summarize("a: ModelAPI provider", logs)


def run_path_b(base_url: str, api_key: str, log_dir: str) -> dict[str, Any]:
    """YOL (b): adapter -> Inspect Custom Agent (solver qatı), model YOXDUR."""
    samples, _ = _samples()
    task = Task(
        dataset=MemoryDataset(samples, name="spike-b"),
        solver=target_agent(
            adapter="dify_http",
            adapter_config={
                "base_url": base_url,
                "api_key": api_key,
                "fetch_tool_traces": True,
            },
        ),
        scorer=agentproof_scorer(),
        name="r1_spike_agent",
    )
    logs = inspect_eval(task, model=None, log_dir=log_dir, display="none", log_level="error")
    return _summarize("b: Custom Agent (solver)", logs)


def main() -> int:
    server = MockDifyServer(scripted=aurora_fixture()).start()
    results: list[dict[str, Any]] = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for label, fn in (("a", run_path_a), ("b", run_path_b)):
                before = len(server.request_log)
                try:
                    result = fn(server.base_url, server.api_key, f"{tmp}/{label}")
                except Exception as e:  # spike: uğursuzluq da nəticədir
                    result = {
                        "path": label,
                        "status": "exception",
                        "error": f"{type(e).__name__}: {e}",
                        "traceback": traceback.format_exc()[-1500:],
                    }
                # ⭐ ƏSAS ÖLÇÜ: 5 case üçün hədəfə neçə sorğu getdi? (ideal: 5)
                result["target_calls"] = len(server.request_log) - before
                results.append(result)
    finally:
        server.stop()

    print(json.dumps(results, indent=2, ensure_ascii=False))
    ok = [r for r in results if r.get("status") == "success" and r.get("n_pass") == r.get("n_total")]
    print("\n--- R1 xulase (5 case) ---")
    for r in results:
        print(
            f"  {r['path']:<28} status={str(r['status']):<8} "
            f"kecen={r.get('n_pass','-')}/{r.get('n_total','-')}  "
            f"hedefe sorgu={r['target_calls']} (ideal 5)"
        )
    print(f"tam kecen yol sayi: {len(ok)}/2")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

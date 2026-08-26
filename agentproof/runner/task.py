"""dataset.jsonl -> Inspect Task (STACK.md §8.4)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from inspect_ai import Task
from inspect_ai.dataset import MemoryDataset, Sample

from agentproof.runner.agent import target_agent
from agentproof.runner.scorer import agentproof_scorer
from agentproof.runner.stages import Stage, filter_stage
from agentproof.types import Case


def load_cases(dataset_path: str | Path) -> list[Case]:
    cases: list[Case] = []
    for line_no, line in enumerate(Path(dataset_path).read_text().splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            cases.append(Case.from_dict(json.loads(line)))
        except (ValueError, KeyError) as e:
            raise ValueError(f"{dataset_path}:{line_no} — dataset sətri oxunmadı: {e}") from e
    ids = [c.id for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"{dataset_path}: təkrarlanan case id-ləri: {sorted(dupes)}")
    return cases


def dataset_hash(cases: Iterable[Case]) -> str:
    payload = json.dumps([c.to_dict() for c in cases], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def parse_filter(expr: str | None) -> list[tuple[str, str]]:
    """`tag=policy,severity=high` -> [("tag","policy"), ("severity","high")]"""
    if not expr:
        return []
    out: list[tuple[str, str]] = []
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"--filter sintaksisi: key=value; alındı: {part!r}")
        key, value = part.split("=", 1)
        out.append((key.strip(), value.strip()))
    return out


def apply_filter(cases: list[Case], expr: str | None) -> list[Case]:
    """Eyni açarın təkrarı VƏ YA, fərqli açarlar VƏ məntiqi ilə birləşir."""
    clauses = parse_filter(expr)
    if not clauses:
        return cases
    by_key: dict[str, list[str]] = {}
    for key, value in clauses:
        by_key.setdefault(key, []).append(value)

    def matches(case: Case, key: str, values: list[str]) -> bool:
        if key == "tag":
            return any(v in case.tags for v in values)
        if key == "severity":
            return case.severity in values
        if key == "grader":
            return case.grader in values
        if key == "id":
            return case.id in values
        raise ValueError(f"naməlum filter açarı: {key!r} (tag|severity|grader|id)")

    return [c for c in cases if all(matches(c, k, v) for k, v in by_key.items())]


def select_cases(
    dataset_path: str | Path,
    filter_expr: str | None = None,
    stage: Stage = "all",
) -> list[Case]:
    """Qaçırılacaq case dəsti — Task qurmadan əvvəl yoxlanır (boş ola bilər)."""
    return filter_stage(apply_filter(load_cases(dataset_path), filter_expr), stage)


def build_task(
    dataset_path: str | Path,
    adapter: str,
    adapter_config: dict[str, Any] | None = None,
    filter_expr: str | None = None,
    stage: Stage = "all",
    repeat: int = 1,
    seed: int | None = None,
    reset_url: str | None = None,
) -> tuple[Task, list[Case]]:
    cases = select_cases(dataset_path, filter_expr, stage)
    if not cases:
        raise ValueError(
            f"{dataset_path}: filter={filter_expr!r} stage={stage!r} heç bir case seçmədi. "
            "Boş qaçış yaşıl nəticə kimi görünməməlidir — `select_cases()` ilə əvvəlcədən yoxla."
        )
    samples = [
        Sample(input=c.query, id=c.id, target="", metadata=c.to_dict()) for c in cases
    ]
    task = Task(
        dataset=MemoryDataset(samples, name=Path(dataset_path).stem),
        solver=target_agent(
            adapter=adapter,
            adapter_config=adapter_config or {},
            repeat=repeat,
            seed=seed,
            reset_url=reset_url,
        ),
        scorer=agentproof_scorer(),
        name="agentproof",
        metadata={
            "dataset_hash": dataset_hash(cases),
            "stage": stage,
            "adapter": adapter,
            "isolation": "admin_reset" if reset_url else "none",
        },
    )
    return task, cases

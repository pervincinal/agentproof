"""Mərhələ bölgüsü — ucuz determinist vs bahalı judge (STACK.md §8.4, 6 dəqiqə qaydası)."""

from __future__ import annotations

from typing import Iterable, Literal

from agentproof.graders import registry
from agentproof.types import Case

Stage = Literal["cheap", "judge", "all"]

STAGE_CHEAP = "cheap"
STAGE_JUDGE = "judge"
STAGE_ALL = "all"


def case_stage(case: Case) -> str:
    return STAGE_JUDGE if registry.kind(case.grader) == "judge" else STAGE_CHEAP


def filter_stage(cases: Iterable[Case], stage: Stage) -> list[Case]:
    if stage == STAGE_ALL:
        return list(cases)
    return [c for c in cases if case_stage(c) == stage]

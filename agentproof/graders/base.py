"""Grader müqaviləsi və registry (STACK.md §8.3).

POZULMAZ QAYDA: bu paket `inspect_ai` import ETMİR.
Yoxlanır: `agentproof/tests/test_no_inspect_import.py`.

Determinist grader-lər şəbəkəyə çıxmır. Şəbəkə lazımdırsa `kind = "judge"`.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from agentproof.types import AgentResponse, Case, GradeResult, GraderKind


@runtime_checkable
class Grader(Protocol):
    name: str
    kind: GraderKind

    def grade(self, case: Case, response: AgentResponse) -> GradeResult: ...


@runtime_checkable
class AggregateGrader(Protocol):
    """`consistency_at_k` kimi çox cavab tələb edənlər."""

    name: str
    kind: GraderKind

    def grade_many(self, case: Case, responses: list[AgentResponse]) -> GradeResult: ...


class _Registry:
    def __init__(self) -> None:
        self._graders: dict[str, Grader | AggregateGrader] = {}

    def add(self, grader: Grader | AggregateGrader) -> None:
        if grader.name in self._graders:
            raise ValueError(f"grader adı təkrarlanır: {grader.name!r}")
        self._graders[grader.name] = grader

    def get(self, name: str) -> Grader | AggregateGrader:
        if name not in self._graders:
            raise KeyError(f"naməlum grader: {name!r}; qeydiyyatda olanlar: {self.names()}")
        return self._graders[name]

    def names(self) -> list[str]:
        return sorted(self._graders)

    def is_aggregate(self, name: str) -> bool:
        return hasattr(self.get(name), "grade_many")

    def kind(self, name: str) -> GraderKind:
        return self.get(name).kind


registry = _Registry()


def grader(cls: type) -> type:
    """Sinfi qeydiyyatdan keçirən dekorator (parametrsiz singleton kimi)."""
    registry.add(cls())
    return cls


# ---------------------------------------------------------------- köməkçilər
def require(case: Case, key: str, grader_name: str) -> object:
    """`expect` açarı yoxdursa dataset xətasıdır — səssiz keçmirik."""
    if key not in case.expect:
        raise ValueError(
            f"case '{case.id}': '{grader_name}' grader-i `expect.{key}` tələb edir, dataset-də yoxdur"
        )
    return case.expect[key]


def normalize(text: str, case_sensitive: bool = False) -> str:
    out = " ".join(text.split())
    return out if case_sensitive else out.lower()


GraderFactory = Callable[[], Grader]

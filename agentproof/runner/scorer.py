"""TƏK scorer — registry-yə dispatch edir.

Yeni grader əlavə etmək bu fayla TOXUNMUR (STACK.md §8.4).
Inspect-i bilən dörd fayldan biridir.
"""

from __future__ import annotations

from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer, stderr
from inspect_ai.solver import TaskState

from agentproof.graders import registry
from agentproof.runner.bridge import pull_responses
from agentproof.types import AgentResponse, Case, GradeResult


def _fallback_response(state: TaskState) -> AgentResponse:
    """Store boşdursa (məs. solver dəyişdirilib) mətnə görə deqradasiya."""
    return AgentResponse(text=state.output.completion if state.output else "")


def grade_state(state: TaskState) -> tuple[Case, GradeResult]:
    """Inspect-dən asılı olmayan hissəni ayrıca funksiyaya çıxarırıq (test üçün)."""
    case = Case.from_dict(state.metadata)
    responses = pull_responses() or [_fallback_response(state)]
    grader = registry.get(case.grader)
    if registry.is_aggregate(case.grader):
        result = grader.grade_many(case, responses)  # type: ignore[union-attr]
    else:
        result = grader.grade(case, responses[-1])  # type: ignore[union-attr]
    return case, result


@scorer(metrics=[accuracy(), stderr()])
def agentproof_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        case, result = grade_state(state)
        responses = pull_responses()
        metadata = {
            "grader": result.grader,
            "grader_kind": registry.kind(case.grader),
            "severity": case.severity,
            "tags": case.tags,
            "skipped": result.skipped,
            "evidence": result.evidence,
            "raw_score": result.score,
            "n_responses": len(responses),
            "latency_ms": responses[-1].latency_ms if responses else 0,
            "usage": responses[-1].usage.to_dict() if responses and responses[-1].usage else None,
            "target_error": responses[-1].error if responses else None,
            "responses": [r.to_dict() for r in responses],
        }
        if result.skipped:
            return Score.unscored(explanation=result.reason, metadata=metadata)
        return Score(
            value=1.0 if result.passed else 0.0,
            answer=(responses[-1].text[:1000] if responses else ""),
            explanation=result.reason,
            metadata=metadata,
        )

    return score

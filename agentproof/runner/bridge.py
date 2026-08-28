"""Inspect körpüsünün ortaq hissəsi — AgentResponse-un daşınması.

Grader-lərə `AgentResponse` bütöv lazımdır (`retrieved[]`, `tool_calls[]`,
`usage`, `latency_ms`, `raw`). Inspect-in `ModelOutput`-u bunu təbii daşımır,
ona görə tam cavab sample store-da saxlanır və scorer oradan oxuyur.
"""

from __future__ import annotations

from typing import Any

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import store

from agentproof.types import AgentResponse

STORE_KEY = "agentproof:responses"
CASE_ID_KEY = "agentproof:case_id"


@solver
def case_context() -> Solver:
    """Case id-sini sample store-a yazır (Task `setup` addımı).

    Inspect agent-ə YALNIZ `state.messages` ötürür (`agent/_as_solver.py`) —
    yəni hədəfə gedən sorğu hansı case-ə aid olduğunu bilmir. Bu, adi halda
    problem deyildi, amma AP-024-dən sonra lazım oldu: `credit_exhausted`
    qaçışı dayandıranda hesabatda "ilk hansı case-də göründü" yazılmalıdır,
    yoxsa səbəb izlənə bilmir.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        case_id = str((state.metadata or {}).get("id", "") or state.sample_id or "")
        store().set(CASE_ID_KEY, case_id)
        return state

    return solve


def current_case_id() -> str:
    """Cari sample-ın case id-si (`case_context()` qaçmayıbsa boş sətir)."""
    return str(store().get(CASE_ID_KEY, "") or "")


def push_response(response: AgentResponse) -> None:
    """Cavabı sample store-a əlavə et (`--repeat` üçün siyahıdır)."""
    responses: list[dict[str, Any]] = list(store().get(STORE_KEY, []))
    responses.append(response.to_dict())
    store().set(STORE_KEY, responses)


def pull_responses() -> list[AgentResponse]:
    return [AgentResponse.from_dict(d) for d in store().get(STORE_KEY, [])]

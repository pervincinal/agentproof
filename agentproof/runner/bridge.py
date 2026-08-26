"""Inspect körpüsünün ortaq hissəsi — AgentResponse-un daşınması.

Grader-lərə `AgentResponse` bütöv lazımdır (`retrieved[]`, `tool_calls[]`,
`usage`, `latency_ms`, `raw`). Inspect-in `ModelOutput`-u bunu təbii daşımır,
ona görə tam cavab sample store-da saxlanır və scorer oradan oxuyur.
"""

from __future__ import annotations

from typing import Any

from inspect_ai.util import store

from agentproof.types import AgentResponse

STORE_KEY = "agentproof:responses"


def push_response(response: AgentResponse) -> None:
    """Cavabı sample store-a əlavə et (`--repeat` üçün siyahıdır)."""
    responses: list[dict[str, Any]] = list(store().get(STORE_KEY, []))
    responses.append(response.to_dict())
    store().set(STORE_KEY, responses)


def pull_responses() -> list[AgentResponse]:
    return [AgentResponse.from_dict(d) for d in store().get(STORE_KEY, [])]

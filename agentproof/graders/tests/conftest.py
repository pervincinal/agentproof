"""Grader testləri üçün ortaq köməkçilər.

Qayda (grader-eng.md): hər grader-in bilərəkdən KEÇƏN və bilərəkdən SINAN
nümunəsi olmalıdır. Test edilməmiş grader sistemi yanlış yaşıla boyayır —
bu, heç bir testin olmamasından pisdir.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentproof.types import AgentResponse, Case, RetrievedChunk, ToolCall, Usage


@pytest.fixture
def make_case():
    def _make(grader: str, expect: dict[str, Any], case_id: str = "t-1", **kw: Any) -> Case:
        return Case(id=case_id, input="sual", grader=grader, expect=expect, **kw)

    return _make


@pytest.fixture
def make_response():
    def _make(
        text: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
        retrieved: list[dict[str, Any]] | None = None,
        usage: dict[str, Any] | None = None,
        latency_ms: int = 120,
    ) -> AgentResponse:
        return AgentResponse(
            text=text,
            tool_calls=[ToolCall(**t) for t in (tool_calls or [])],
            retrieved=[RetrievedChunk(**r) for r in (retrieved or [])],
            usage=Usage(**usage) if usage else None,
            latency_ms=latency_ms,
        )

    return _make

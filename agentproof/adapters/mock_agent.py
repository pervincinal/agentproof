"""In-process mock adapter — şəbəkəsiz determinist hədəf.

`http_agent` ilə eyni müqaviləni doldurur, amma HTTP-yə çıxmır. Grader unit
testləri və harness-in öz testləri üçün. Wire formatının özünü sınamaq
lazım olanda `agentproof.testing.mock_dify` + `dify_http` istifadə olunur.
"""

from __future__ import annotations

import time
from typing import Any

from agentproof.adapters.base import register_adapter
from agentproof.types import AgentRequest, AgentResponse, RetrievedChunk, ToolCall, Usage


class MockAgent:
    name = "mock"

    def __init__(self, scripted: dict[str, dict[str, Any]] | None = None, version: str = "mock-1") -> None:
        self.scripted = scripted or {}
        self.version = version

    async def health(self) -> bool:
        return True

    async def invoke(self, req: AgentRequest) -> AgentResponse:
        started = time.perf_counter()
        spec = self._match(req.query)
        latency_ms = spec.get("latency_ms", int((time.perf_counter() - started) * 1000))
        return AgentResponse(
            text=spec.get("answer", ""),
            tool_calls=[ToolCall.from_dict(t) for t in spec.get("tool_calls", [])],
            retrieved=[
                RetrievedChunk(
                    chunk_id=r.get("chunk_id", ""),
                    text=r.get("content", r.get("text", "")),
                    score=r.get("score"),
                    document=r.get("document", ""),
                )
                for r in spec.get("retrieved", [])
            ],
            usage=Usage(**spec["usage"]) if spec.get("usage") else None,
            latency_ms=latency_ms,
            raw={"scripted": True},
            error=spec.get("error"),
        )

    def _match(self, query: str) -> dict[str, Any]:
        q = query.lower()
        for needle, spec in self.scripted.items():
            if needle.lower() in q:
                return spec
        return {"answer": ""}


@register_adapter("mock")
def mock(**config: Any) -> MockAgent:
    return MockAgent(**config)

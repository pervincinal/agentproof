"""In-process mock adapter — şəbəkəsiz determinist hədəf.

`http_agent` ilə eyni müqaviləni doldurur, amma HTTP-yə çıxmır. Grader unit
testləri və harness-in öz testləri üçün. Wire formatının özünü sınamaq
lazım olanda `agentproof.testing.mock_dify` + `dify_http` istifadə olunur.

Müqavilə şərtləri (AP-028, `adapters/conformance.py`) burada da keçərlidir —
mock "sadələşdirilmiş qayda" ilə yaşamır:

  * `usage` skriptdə yoxdursa `None` (sıfır DEYİL);
  * boş cavab SƏSSİZ keçmir — `empty_answer` adı ilə görünür;
  * `error` varsa, `error_class` da doldurulur (`failure.classify_failure`).

Mock ŞƏBƏKƏYƏ ÇIXMIR, ona görə backoff/təkrar və çoxnövbəli `conversation_id`
zənciri ONDA YOXDUR: təkrar ediləcək nəqliyyat xətası da, zəncirlənəcək söhbət
də mövcud deyil. Bu boşluq gizlədilmir — `test_adapter_conformance.py`-dəki
dəstək matrisi onu adı ilə sayır.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from agentproof.adapters.base import register_adapter
from agentproof.failure import classify_failure
from agentproof.types import AgentRequest, AgentResponse, RetrievedChunk, ToolCall, Usage


class MockAgent:
    name = "mock"

    def __init__(
        self, scripted: dict[str, dict[str, Any]] | None = None, version: str = "mock-1"
    ) -> None:
        self.scripted = scripted or {}
        self.version = version
        #: Hədəfə neçə çağırış getdi — uyğunluq dəsti təkrarı bununla sayır.
        self.calls = 0

    async def health(self) -> bool:
        return True

    async def invoke(self, req: AgentRequest) -> AgentResponse:
        self.calls += 1
        started = time.perf_counter()
        spec = self._match(req.query)
        if spec.get("delay_ms"):
            await asyncio.sleep(float(spec["delay_ms"]) / 1000.0)
        latency_ms = spec.get("latency_ms", int((time.perf_counter() - started) * 1000))
        text = spec.get("answer", "")
        # Boş cavab ADLANDIRILIR: adlanmasaydı, grader onu "yanlış məzmun" kimi
        # sayardı və hesabat hədəfi işləməyən infrastruktura görə cəzalandırardı.
        error = spec.get("error") or (None if text.strip() else "empty_answer")
        return AgentResponse(
            text=text,
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
            # Skriptdə `usage` yoxdursa `None` — "ölçülmədi", sıfır deyil.
            usage=Usage(**spec["usage"]) if spec.get("usage") else None,
            latency_ms=latency_ms,
            raw={"scripted": True, "attempts": 1},
            error=error,
            # `error` NƏ baş verdiyini deyir, `error_class` NƏ ETMƏLİ olduğunu.
            error_class=(
                classify_failure(
                    code=error,
                    message=str(spec.get("error_message", "")),
                    status=spec.get("error_status"),
                )
                if error
                else None
            ),
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

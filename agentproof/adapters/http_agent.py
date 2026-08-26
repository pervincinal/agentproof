"""Dify `POST /v1/chat-messages` adapteri (SETUP.md §7.2).

Konfiqurasiya YALNIZ mühit dəyişənlərindən / CLI-dan gəlir — açar koda yazılmır
və loga düşmür. Real açar olmadan da işə düşür: `health()` False qaytarır.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import httpx

from agentproof.adapters.base import register_adapter
from agentproof.types import AgentRequest, AgentResponse, RetrievedChunk, ToolCall, Usage

# SETUP.md §7.2 — bunlar hədəfin infrastruktur xətalarıdır, məzmun uğursuzluğu deyil
DIFY_INFRA_ERRORS = {
    "provider_not_initialize",
    "provider_quota_exceeded",
    "too_many_requests",
    "rate_limit_error",
    "completion_request_error",
    "unauthorized",
}


class DifyHttpAgent:
    name = "dify_http"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        version: str = "1.17.0",
        user: str = "agentproof-eval-runner",
        timeout_s: float = 120.0,
        fetch_tool_traces: bool = True,
    ) -> None:
        self.base_url = (base_url or os.environ.get("DIFY_BASE_URL", "http://localhost:8088/v1")).rstrip("/")
        self._api_key = api_key or os.environ.get("DIFY_API_KEY", "")
        self.version = version
        self.user = user
        self.timeout_s = timeout_s
        self.fetch_tool_traces = fetch_tool_traces

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    async def health(self) -> bool:
        if not self._api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self.base_url}/info", headers=self._headers())
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def invoke(self, req: AgentRequest) -> AgentResponse:
        payload = {
            "inputs": req.metadata.get("inputs", {}),
            "query": req.query,
            "response_mode": "blocking",
            # hər case üçün boş: case-lər bir-birini çirkləndirməsin (SETUP.md §7.2)
            "conversation_id": "",
            "user": f"{self.user}-{req.session_id or uuid.uuid4().hex[:8]}",
        }
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(f"{self.base_url}/chat-messages", headers=self._headers(), json=payload)
            latency_ms = int((time.perf_counter() - started) * 1000)
            body = _safe_json(r)
            if r.status_code != 200:
                code = body.get("code", f"http_{r.status_code}")
                return AgentResponse(
                    text="",
                    latency_ms=latency_ms,
                    raw=body,
                    error=code if code in DIFY_INFRA_ERRORS else f"unexpected:{code}",
                )
            tool_calls: list[ToolCall] = []
            if self.fetch_tool_traces and body.get("conversation_id"):
                tool_calls = await self._tool_traces(client, body["conversation_id"])

        meta = body.get("metadata", {}) or {}
        return AgentResponse(
            text=body.get("answer", ""),
            tool_calls=tool_calls,
            retrieved=[
                RetrievedChunk(
                    chunk_id=str(rr.get("segment_id") or rr.get("document_id") or ""),
                    text=rr.get("content", ""),
                    score=rr.get("score"),
                    document=rr.get("document_name", ""),
                )
                for rr in meta.get("retriever_resources", []) or []
            ],
            usage=_usage(meta.get("usage")),
            latency_ms=latency_ms,
            raw=body,
        )

    async def _tool_traces(self, client: httpx.AsyncClient, conversation_id: str) -> list[ToolCall]:
        """Agent tool izləri `GET /v1/messages`-dəki `agent_thoughts`-dan gəlir."""
        try:
            r = await client.get(
                f"{self.base_url}/messages",
                headers=self._headers(),
                params={"conversation_id": conversation_id, "user": self.user, "limit": 1},
            )
            if r.status_code != 200:
                return []
            messages = _safe_json(r).get("data", []) or []
        except httpx.HTTPError:
            return []
        calls: list[ToolCall] = []
        for msg in messages:
            for thought in msg.get("agent_thoughts", []) or []:
                name = thought.get("tool") or ""
                if not name:
                    continue
                calls.append(
                    ToolCall(
                        name=name,
                        arguments=_tool_args(name, thought.get("tool_input")),
                        result=_maybe_json(thought.get("observation")),
                    )
                )
        return calls


def _safe_json(r: httpx.Response) -> dict[str, Any]:
    try:
        data = r.json()
        return data if isinstance(data, dict) else {"data": data}
    except ValueError:
        return {"code": "invalid_response", "message": r.text[:500]}


def _maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value


def _tool_args(name: str, tool_input: Any) -> dict[str, Any]:
    """Dify `tool_input`-u `{"tool_name": {...args}}` şəklində verir."""
    parsed = _maybe_json(tool_input)
    if isinstance(parsed, dict):
        inner = parsed.get(name)
        if isinstance(inner, dict):
            return inner
        return parsed
    return {}


def _usage(u: dict[str, Any] | None) -> Usage | None:
    if not u:
        return None
    return Usage(
        input_tokens=int(u.get("prompt_tokens", 0)),
        output_tokens=int(u.get("completion_tokens", 0)),
        model=u.get("model", ""),
    )


@register_adapter("dify_http")
def dify_http(**config: Any) -> DifyHttpAgent:
    return DifyHttpAgent(**config)

"""Şəbəkəsiz saxta agent qrafı — `callable` adapterini sınamaq üçün (AP-031).

`mock_agent.py` skriptləşdirilmiş LÜĞƏTDİR: adapterin özü heç nə çağırmır.
Burada isə REAL çağırış var — sadəcə çağırılan şey prosesin içindədir. Qraf
LangGraph/LlamaIndex hədəflərinin üç xüsusiyyətini təqlid edir:

  1. **söhbət yaddaşı** — tarixçə `conversation_id` üzrə saxlanılır, cavab
     əvvəlki növbələrdən asılıdır (kontekst itkisi məhz burada ölçülür);
  2. **tool çağırışı** — cavabla birlikdə hansı funksiyanın işlədiyi qayıdır;
  3. **SDK istisnaları** — xəta `return` ilə deyil, `raise` ilə gəlir və
     statusu ÖZÜ daşıyır (`status_code`), çünki real SDK-lar belə davranır.

Qaytarılan lüğətin sahə adları QƏSDƏN qeyri-standartdır (`reply`, `spend`,
`used_tools`, `refs`): `callable` adapteri də sahə xəritəsi ilə qoşulur və
default namizədlərə söykənməməlidir.
"""

from __future__ import annotations

import time
from typing import Any, Callable

#: `FieldMap` konfiqurasiyası — qrafın öz adlandırması.
GRAPH_MAP: dict[str, Any] = {
    "text_path": "reply",
    "usage_path": "spend",
    "usage_input_path": "prompt",
    "usage_output_path": "generated",
    "tool_calls_path": "used_tools",
    "tool_name_path": "fn",
    "tool_arguments_path": "params",
    "tool_result_path": "returned",
    "retrieved_path": "refs",
    "chunk_id_path": "anchor",
    "chunk_text_path": "body",
    "chunk_score_path": "rank",
    "chunk_document_path": "file",
}


class GraphError(RuntimeError):
    """SDK istisnası: statusu özü daşıyır."""

    status_code: int | None = None


class RateLimited(GraphError):
    status_code = 429


class Unauthorized(GraphError):
    status_code = 401


class InvalidRequest(GraphError):
    status_code = 400


class UpstreamError(GraphError):
    """Upstream model xətası — səbəb MESAJIN içindədir (Dify-dakı kimi)."""

    status_code = 400


EXCEPTIONS: dict[str, type[GraphError]] = {
    "rate_limited": RateLimited,
    "unauthorized": Unauthorized,
    "invalid_request": InvalidRequest,
    "upstream": UpstreamError,
}


class FakeSupportGraph:
    """Yaddaşı olan in-process agent.

    `scripted` formatı (açar sorğuda axtarılan alt sətir):
        {
          "answer": str,
          "usage": {"input_tokens", "output_tokens"},
          "tool_calls": [{"name","arguments","result"}],
          "retrieved": [{"chunk_id","content","score","document"}],
          "delay_ms": int,
          "raises": ("rate_limited"|"unauthorized"|"invalid_request"|"upstream", message),
          "side_effect": callable(query, history) -> dict | None,
        }
    """

    def __init__(self, scripted: dict[str, dict[str, Any]] | None = None,
                 default: dict[str, Any] | None = None) -> None:
        self.scripted = scripted or {}
        self.default = default or {"answer": ""}
        self.calls = 0
        self.history: dict[str, list[str]] = {}

    # `conversation_id` parametrinin ADI vacibdir: `callable_agent` çoxnövbəli
    # dəstəyi məhz imzadan oxuyur (təxmin etmir).
    def answer(self, query: str, conversation_id: str = "") -> dict[str, Any]:
        self.calls += 1
        spec = dict(self._match(query))
        turns = self.history.setdefault(conversation_id, [])
        turns.append(query)

        side_effect: Callable[..., Any] | None = spec.get("side_effect")
        if callable(side_effect):
            override = side_effect(query, list(turns))
            if isinstance(override, dict):
                spec.update(override)

        if spec.get("delay_ms"):
            time.sleep(float(spec["delay_ms"]) / 1000.0)

        if spec.get("raises"):
            kind, message = spec["raises"]
            raise EXCEPTIONS[kind](message)

        body: dict[str, Any] = {"reply": spec.get("answer", "")}
        if "usage" in spec:
            body["spend"] = {
                "prompt": spec["usage"].get("input_tokens", 0),
                "generated": spec["usage"].get("output_tokens", 0),
            }
        if "tool_calls" in spec:
            body["used_tools"] = [
                {"fn": t["name"], "params": t.get("arguments", {}), "returned": t.get("result")}
                for t in spec["tool_calls"]
            ]
        if "retrieved" in spec:
            body["refs"] = [
                {
                    "anchor": r.get("chunk_id", ""),
                    "body": r.get("content", r.get("text", "")),
                    "rank": r.get("score"),
                    "file": r.get("document", ""),
                }
                for r in spec["retrieved"]
            ]
        return body

    async def aanswer(self, query: str, conversation_id: str = "") -> dict[str, Any]:
        """Async variant — adapter hər ikisini qəbul etməlidir."""
        return self.answer(query, conversation_id)

    def _match(self, query: str) -> dict[str, Any]:
        q = query.lower()
        for needle, spec in self.scripted.items():
            if needle.lower() in q:
                return spec
        return self.default

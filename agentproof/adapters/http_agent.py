"""Dify `POST /v1/chat-messages` adapteri — HTTP nəqliyyatı və konfiqurasiya.

Fayl ÜÇ qatın yalnız birini saxlayır (AP-029):

  bu fayl              -> Dify HTTP müştərisi: sorğu gövdəsi, başlıqlar,
                          `health()`, timeout, model etiketi
  `_dify_wire.py`      -> Dify SSE wire formatı (event adları, `dify_error`,
                          `agent_thought`, tool ardıcıllığı)
  `_http_core.py`      -> Dify-dən ASILI OLMAYAN nüvə: backoff/təkrar (AP-024),
                          yanan tokenlərin yığımı (AP-026), çoxnövbəli
                          `conversation_id` zənciri və növbələrin birləşməsi

Əvvəl hər üçü bir yerdə — 786 sətir — idi. Nəticədə ikinci adapter yazılan an
(b) və (c) sıfırdan təkrarlanmalı olardı və hər təkrarda fərqli sınardı.
`base.py`-dəki "yeni müştəri = bir adapter faylı" vədi məhz bu ayrılıqla
doğrudur.

⚠️ `blocking` DƏSTƏKLƏNMİR. Agent Chat app-i icra yolunun dibində rədd edir:

    core/app/apps/agent_chat/app_generator.py:94
        raise ValueError("Agent Chat App does not support blocking mode")

Canlı sistemdə 400 `invalid_param` ilə təsdiqləndi (PLAN.md "DÜZƏLİŞ").
Ona görə adapter YALNIZ `response_mode: streaming` göndərir.

Konfiqurasiya YALNIZ mühit dəyişənlərindən / CLI-dan gəlir — açar koda yazılmır
və loga düşmür. Real açar olmadan da işə düşür: `health()` False.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import httpx

from agentproof.adapters import _dify_wire as wire
from agentproof.adapters._http_core import (
    RetryPolicy,
    merge_turns,
    run_conversation,
    send_with_retry,
    user_turns,
)
from agentproof.adapters.base import register_adapter
from agentproof.types import AgentRequest, AgentResponse

# Köhnə idxal yolları qırılmasın deyə wire sabitləri burada da görünür.
DIFY_INFRA_ERRORS = wire.DIFY_INFRA_ERRORS
STREAM_ERRORS = wire.STREAM_ERRORS
TOOL_SEPARATOR = wire.TOOL_SEPARATOR


class DifyHttpAgent:
    name = "dify_http"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        version: str = "1.17.0",
        user: str = "agentproof-eval-runner",
        timeout_s: float = 180.0,
        model: str | None = None,
        max_rate_limit_retries: int | None = None,
        backoff_base_s: float | None = None,
        backoff_cap_s: float | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("DIFY_BASE_URL", "http://localhost:8088/v1")
        ).rstrip("/")
        self._api_key = api_key or os.environ.get("DIFY_API_KEY", "")
        self.version = version
        self.user = user
        self.timeout_s = timeout_s
        # Dify `metadata.usage`-da model ADI GƏLMİR (canlı axında təsdiqləndi).
        # Etiket kənardan verilir; verilmirsə `usage.model` boş qalır və
        # `cost_under` `skipped` olur — səssiz keçmir (PLAN.md risk #2).
        self.model = model if model is not None else os.environ.get("AGENTPROOF_SUT_MODEL", "")
        # Backoff parametrləri (AP-024) — mühitdən oxunur, açar kimi CLI-a düşmür.
        self.retry = RetryPolicy.from_config(
            max_rate_limit_retries, backoff_base_s, backoff_cap_s
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

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
        """Case-in BÜTÜN istifadəçi növbələrini bir söhbətdə göndərir.

        Zəncirin, backoff-un və birləşmənin özü nüvədədir. Burada yalnız
        Dify-ə xas olan `user` sahəsi qurulur: söhbət son istifadəçiyə
        bağlandığı üçün o, növbədən növbəyə DƏYİŞMƏMƏLİDİR — dəyişsə, zəncir
        sükutla qırılardı.

        Tək növbəli case-də davranış əvvəlki ilə eynidir (bir sorğu,
        `conversation_id: ""`).
        """
        queries, dropped = user_turns(req.messages, req.query)
        end_user = f"{self.user}-{req.session_id or uuid.uuid4().hex[:8]}"
        case_id = str(req.metadata.get("case_id", "")) if req.metadata else ""

        async def turn(query: str, conversation_id: str, index: int) -> AgentResponse:
            return await send_with_retry(
                lambda: self._send_once(req, query, conversation_id, end_user, index),
                policy=self.retry,
                model=self.model,
                case_id=case_id,
                detail=wire.error_detail,
                # Qaçış dayandırılıbsa, göndərilməyən sorğu da ADLA qeyd olunur.
                context={
                    "turn_index": index,
                    "sent_conversation_id": conversation_id,
                    "query": query,
                },
            )

        turns = await run_conversation(turn, queries)
        return merge_turns(turns, dropped, model=self.model, transport=wire.TRANSPORT)

    async def _send_once(
        self,
        req: AgentRequest,
        query: str,
        conversation_id: str,
        end_user: str,
        turn_index: int,
    ) -> AgentResponse:
        """BİR HTTP sorğusu + SSE axınının oxunması. Təkrar BURADA YOXDUR."""
        payload = {
            "inputs": req.metadata.get("inputs", {}),
            "query": query,
            # Agent Chat `blocking`-i 400 ilə rədd edir — bax modul docstring-i.
            "response_mode": "streaming",
            # İLK növbədə boş: case-lər bir-birini çirkləndirməsin (SETUP.md §7.2).
            # Sonrakı növbələrdə əvvəlki cavabdan gələn id — söhbət ZƏNCİRLƏNİR.
            "conversation_id": conversation_id,
            "user": end_user,
        }
        state = wire.StreamState()
        transport_error = ""
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat-messages",
                    headers=self._headers(),
                    json=payload,
                ) as r:
                    if r.status_code != 200:
                        raw = await r.aread()
                        return wire.response_from_http_error(
                            raw,
                            r.status_code,
                            int((time.perf_counter() - started) * 1000),
                            turn_index,
                            retry_after=r.headers.get("Retry-After"),
                        )
                    async for line in r.aiter_lines():
                        wire.consume_line(state, line)
        except httpx.TimeoutException:
            transport_error = "stream_timeout"
        except httpx.RemoteProtocolError:
            # axın yarımçıq kəsildi (chunk bitmədən bağlantı bağlandı)
            transport_error = "stream_incomplete"
        except httpx.HTTPError:
            transport_error = "stream_transport"

        latency_ms = int((time.perf_counter() - started) * 1000)
        turn = wire.response_from_stream(state, transport_error, latency_ms, self.model)
        turn.raw["turn_index"] = turn_index
        turn.raw["sent_conversation_id"] = conversation_id
        turn.raw["query"] = query
        return turn


@register_adapter("dify_http")
def dify_http(**config: Any) -> DifyHttpAgent:
    return DifyHttpAgent(**config)

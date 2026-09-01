"""Bloklayıcı JSON HTTP adapteri — `POST` -> bir JSON cavab (AP-030).

`http_agent.py` SSE-yə MƏCBURİYYƏTDƏN bağlıdır: Dify Agent Chat `blocking`
rejimini icra yolunun dibində rədd edir. Bu, Dify-ın xüsusiyyətidir, sənayenin
qaydası deyil. Müştərinin öz FastAPI-si, LangGraph-ın `/invoke` endpoint-i və
ya Vercel AI SDK route-u adətən ən sadə formanı verir:

    POST /invoke  {"query": "..."}   ->   200 {"output": "...", "usage": {...}}

Bu adapter həmin formanı ölçür. Heç bir framework SDK-sından asılı deyil —
fərq YALNIZ sahə adlarındadır və onlar konfiqurasiyadadır (`_field_map.py`).

QATLAR (AP-029 sərhədi)
-----------------------
    bu fayl            HTTP müştərisi: URL, başlıqlar, gövdə, `health()`
    `_field_map.py`    sahə adları -> müqavilə sahələri (hədəfdən asılı deyil)
    `_http_core.py`    backoff/təkrar, HALT, çoxnövbəli zəncir, növbə birləşməsi

Nüvə YENİDƏN YAZILMIR. `full-run-03`-ün dərsləri (kredit xətası ilə rate
limit-in fərqi, atılan cəhdin tokeni, çoxnövbəli case-in tək-növbəli kimi
ölçülməsi) burada bir daha kəşf edilmir — idxal olunur.

ÇOXNÖVBƏLİ: TƏXMİN YOXDUR
-------------------------
`conversation_id_path` verilməyibsə adapter söhbəti zəncirləyə bilmir və bunu
DEYİR: çoxnövbəli case `multi_turn_unsupported` ilə qayıdır, sorğu
göndərilmir. Səssizcə tək-növbəli ölçmək 15 case-i yalan yaşıl edərdi.

Qoşulma nümunəsi: `docs/ADAPTERS.md` və README "Connect your own system".
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import httpx

from agentproof.adapters._field_map import FieldMap, build_response, error_detail
from agentproof.adapters._http_core import (
    RetryPolicy,
    json_or_text,
    merge_turns,
    multi_turn_unsupported_response,
    run_conversation,
    send_with_retry,
    user_turns,
)
from agentproof.adapters.base import register_adapter
from agentproof.failure import classify_failure
from agentproof.types import UNKNOWN, AgentRequest, AgentResponse

TRANSPORT = "json"

#: Nəqliyyat səviyyəsində baş verən və hədəfin CAVABI OLMAYAN xətalar.
#: Bunlar məzmun uğursuzluğu DEYİL — hesabatda ayrıca sayılmalıdır.
REQUEST_TIMEOUT = "request_timeout"      # `timeout_s` doldu
REQUEST_TRANSPORT = "request_transport"  # DNS / bağlantı / TLS
TRANSPORT_ERRORS = frozenset({REQUEST_TIMEOUT, REQUEST_TRANSPORT})


class JsonHttpAgent:
    """Bloklayıcı JSON hədəfi. Sahə adları konfiqurasiya ilə verilir."""

    name = "json_http"

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        auth_header: str = "Authorization",
        auth_scheme: str = "Bearer",
        headers: dict[str, str] | None = None,
        method: str = "POST",
        # Hədəfin versiyası KƏNARDAN verilir. Verilməsə `unknown` qalır —
        # boş sətir "sahə boşdur" kimi oxunardı, `unknown` isə "ölçülmədi".
        version: str = UNKNOWN,
        timeout_s: float = 120.0,
        model: str | None = None,
        query_field: str = "query",
        conversation_field: str = "conversation_id",
        user_field: str = "user",
        user: str = "agentproof-eval-runner",
        extra_body: dict[str, Any] | None = None,
        health_url: str | None = None,
        max_rate_limit_retries: int | None = None,
        backoff_base_s: float | None = None,
        backoff_cap_s: float | None = None,
        **paths: Any,
    ) -> None:
        self.url = (url or os.environ.get("AGENTPROOF_JSON_URL", "")).strip()
        self._api_key = api_key or os.environ.get("AGENTPROOF_JSON_API_KEY", "")
        self.auth_header = auth_header
        self.auth_scheme = auth_scheme
        self.extra_headers = dict(headers or {})
        self.method = method.upper()
        self.version = version
        self.timeout_s = timeout_s
        # Hədəf `usage`-da model adı verməyə bilər; etiket kənardan gəlir.
        # Verilməsə `usage.model` boş qalır və `cost_under` `skipped` olur.
        self.model = model if model is not None else os.environ.get("AGENTPROOF_SUT_MODEL", "")
        self.query_field = query_field
        self.conversation_field = conversation_field
        self.user_field = user_field
        self.user = user
        self.extra_body = dict(extra_body or {})
        self.health_url = health_url
        #: Sahə xəritəsi. Tanınmayan açar `TypeError` verir — yazı səhvi
        #: susqun default-a düşməsin.
        self.map = FieldMap.from_config(**paths)
        self.retry = RetryPolicy.from_config(
            max_rate_limit_retries, backoff_base_s, backoff_cap_s
        )
        if not self.url:
            raise ValueError(
                "json_http: `url` verilməyib (və ya `AGENTPROOF_JSON_URL` boşdur)"
            )

    # ------------------------------------------------------------ nəqliyyat
    def _headers(self) -> dict[str, str]:
        head = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            prefix = f"{self.auth_scheme} " if self.auth_scheme else ""
            head[self.auth_header] = f"{prefix}{self._api_key}"
        head.update(self.extra_headers)
        return head

    async def health(self) -> bool:
        """Hədəf əlçatandırmı.

        `health_url` VERİLİBSƏ o ünvan yoxlanılır və yalnız 200 `True` sayılır
        (hədəf öz hazırlığını elan edir). Verilməyibsə çağırış ünvanına `GET`
        gedir və HƏR HTTP cavabı (405 daxil) `True` sayılır: bu, yalnız
        "server ayaqdadır" deməkdir, "agent hazırdır" DEMİR — fərq
        `preflight`-ın 1-ci sətrində ADI ilə yazılır.
        """
        target = self.health_url or self.url
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(target, headers=self._headers())
        except httpx.HTTPError:
            return False
        if self.health_url:
            return r.status_code == 200
        return r.status_code < 500

    # --------------------------------------------------------------- invoke
    async def invoke(self, req: AgentRequest) -> AgentResponse:
        queries, dropped = user_turns(req.messages, req.query)
        if len(queries) > 1 and not self.map.supports_multi_turn:
            # Zəncir qurula bilmir -> ÖLÇMÜRÜK və bunu deyirik.
            return multi_turn_unsupported_response(
                len(queries),
                detail=(
                    "json_http: `conversation_id_path` konfiqurasiya edilməyib — "
                    "söhbət zəncirlənə bilmir, çoxnövbəli case ölçülmür"
                ),
                transport=TRANSPORT,
            )
        end_user = f"{self.user}-{req.session_id or uuid.uuid4().hex[:8]}"
        case_id = str(req.metadata.get("case_id", "")) if req.metadata else ""

        async def turn(query: str, conversation_id: str, index: int) -> AgentResponse:
            return await send_with_retry(
                lambda: self._send_once(req, query, conversation_id, end_user, index),
                policy=self.retry,
                model=self.model,
                case_id=case_id,
                detail=error_detail,
                context={
                    "turn_index": index,
                    "sent_conversation_id": conversation_id,
                    "query": query,
                },
            )

        turns = await run_conversation(turn, queries)
        return merge_turns(turns, dropped, model=self.model, transport=TRANSPORT)

    async def _send_once(
        self,
        req: AgentRequest,
        query: str,
        conversation_id: str,
        end_user: str,
        turn_index: int,
    ) -> AgentResponse:
        """BİR HTTP sorğusu. Təkrar BURADA YOXDUR (nüvədədir)."""
        payload: dict[str, Any] = {
            **self.extra_body,
            **(req.metadata.get("inputs", {}) if req.metadata else {}),
            self.query_field: query,
        }
        if self.user_field:
            payload[self.user_field] = end_user
        if self.map.supports_multi_turn:
            # İlk növbədə boş: case-lər bir-birini çirkləndirməsin.
            payload[self.conversation_field] = conversation_id

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                r = await client.request(
                    self.method, self.url, headers=self._headers(), json=payload
                )
            latency_ms = int((time.perf_counter() - started) * 1000)
            body = json_or_text(r.content)
            turn = build_response(
                body,
                self.map,
                latency_ms=latency_ms,
                model=self.model,
                transport=TRANSPORT,
                http_status=r.status_code,
                retry_after=r.headers.get("Retry-After"),
            )
        except httpx.TimeoutException:
            turn = _transport_failure(REQUEST_TIMEOUT, started)
        except httpx.HTTPError:
            turn = _transport_failure(REQUEST_TRANSPORT, started)

        turn.raw["turn_index"] = turn_index
        turn.raw["sent_conversation_id"] = conversation_id
        turn.raw["query"] = query
        return turn


def _transport_failure(kind: str, started: float) -> AgentResponse:
    """Cavab ÜMUMİYYƏTLƏ gəlmədi — boş mətn səssiz qaytarılmır."""
    return AgentResponse(
        text="",
        latency_ms=int((time.perf_counter() - started) * 1000),
        raw={"transport": TRANSPORT, "target_error": {"code": kind, "message": "", "status": None}},
        error=kind,
        # Nəqliyyat xətası təsnif olunmur: 429 deyil, auth deyil — `unknown`.
        # Təxmin etsək, gözləməli olmayan yerdə gözləyərdik.
        error_class=classify_failure(code=kind),
    )



@register_adapter("json_http")
def json_http(**config: Any) -> JsonHttpAgent:
    return JsonHttpAgent(**config)

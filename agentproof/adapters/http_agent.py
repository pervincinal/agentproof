"""Dify `POST /v1/chat-messages` adapteri — SSE (streaming) yolu.

⚠️ `blocking` DƏSTƏKLƏNMİR. Agent Chat app-i icra yolunun dibində rədd edir:

    core/app/apps/agent_chat/app_generator.py:94
        raise ValueError("Agent Chat App does not support blocking mode")

Canlı sistemdə 400 `invalid_param` ilə təsdiqləndi (PLAN.md "DÜZƏLİŞ").
Ona görə adapter YALNIZ `response_mode: streaming` göndərir və SSE axınını
özü yığır.

Konfiqurasiya YALNIZ mühit dəyişənlərindən / CLI-dan gəlir — açar koda
yazılmır və loga düşmür. Real açar olmadan da işə düşür: `health()` False.

Axından çıxarılanlar:
  agent_message / message  -> yekun cavab mətni (parça-parça gəlir)
  agent_thought            -> tool çağırışlarının ARDICILLIĞI (`tool_call_matches`)
  message_end.metadata.usage               -> token + xərc (`cost_under`)
  message_end.metadata.retriever_resources -> retrieval (`retrieval_hit_at_k`)
  error                    -> hədəfin öz xəta zərfi

Səssiz boş cavab YOXDUR: yarımçıq axın, timeout, transport xətası və boş
cavab — hamısı `AgentResponse.error` sahəsində ADLA görünür.

XƏTA SİNFİ VƏ BACKOFF (AP-024)
------------------------------
`error` NƏ baş verdiyini deyir, `error_class` isə NƏ ETMƏLİ olduğunu
(`agentproof/failure.py`). `full-run-03`-də 25 case eyni
`completion_request_error` kodu altında `skipped` oldu, halbuki səbəblər
fərqli idi: 24-ü "credit balance is too low" (gözləməklə KEÇMİR), Dify
loglarında isə ayrıca 429/529 (gözləməklə KEÇİR).

  * `rate_limit`       -> eksponensial backoff + təkrar (`Retry-After` varsa ona
                          hörmət). Cəhdlər bitsə case `skipped` qalır, amma
                          səbəb `rate_limit` kimi kodlanır.
  * `credit_exhausted` -> təkrar YOXDUR və QAÇIŞ BÜTÖVLÜKDƏ DAYANIR (`HALT`):
                          növbəti 100 case-i də sındırmağın mənası yoxdur.
  * `auth`             -> təkrar YOXDUR (gözləmək kömək etmir).

Təkrar cəhdlərin tokenləri itmir: atılan cavabın `usage`-ı `retry_usage`-a
yığılır və hesabatda `wasted_cost_usd` kimi görünür (AP-026).

ÇOXNÖVBƏLİ SÖHBƏT
-----------------
`req.messages` bir neçə istifadəçi növbəsi daşıyırsa, adapter onları BİR
söhbətdə ardıcıl göndərir: ilk növbə `conversation_id: ""` ilə gedir, cavabdan
qayıdan `conversation_id` sonrakı bütün növbələrə yazılır. Bu olmasa hər növbə
ayrı söhbət açardı və `full.jsonl`-dəki 15 çoxnövbəli case tək-növbəli kimi
ölçülərdi — yəni C1 (kontekst itkisi, P=20) rəqəmi hesabatda görünər, amma
YALAN olardı (`evals/datasets/COVERAGE.md §7`).

Zəncir qırılarsa qaçış SƏSSİZCƏ davam etmir:
  * bir növbə xəta qaytarsa, qalan növbələr GÖNDƏRİLMİR (`error` saxlanılır);
  * ilk növbə `conversation_id` qaytarmasa və daha növbə varsa,
    `conversation_not_returned` xətası verilir — yeni söhbətlə davam etmək
    çoxnövbəli case-i gizlicə tək-növbəliyə çevirmək demək olardı.

Dataset-də skriptləşdirilmiş `assistant` növbəsi varsa, o, GÖNDƏRİLMİR (Dify
söhbət tarixçəsini özü qurur; kənardan assistant mesajı yeritmək mümkün deyil).
Bu, `raw.dropped_scripted_assistant_turns`-də sayılır — susqun qalmır.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from agentproof.adapters.base import register_adapter
from agentproof.failure import (
    HALT,
    HALTING,
    REASON_HINT,
    RETRYABLE,
    classify_failure,
)
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

# Axının özündən doğan xətalar — hədəfin məzmun cavabı deyil, nəqliyyat problemi.
STREAM_ERRORS = {
    "stream_incomplete",   # `message_end` gəlmədi (bağlantı yarımçıq kəsildi)
    "stream_timeout",      # `timeout_s` doldu
    "stream_transport",    # şəbəkə səviyyəsində xəta
    "stream_unreadable",   # gələn sətirlərin hamısı parse olunmadı
}

# `agent_thought.tool` bir neçə tool-u nöqtəli vergüllə birləşdirir:
#   "check_return_eligibility;dataset_e1471e22_..."  (paralel çağırış)
TOOL_SEPARATOR = ";"

# Mətn daşıyan event növləri: agent app -> agent_message, adi chat -> message.
TEXT_EVENTS = {"agent_message", "message"}

# --- backoff (AP-024) ------------------------------------------------------
# YALNIZ `rate_limit` sinfi üçün. `credit_exhausted` və `auth` yenidən cəhd
# EDİLMİR: onlar gözləməklə keçmir, hər təkrar sadəcə pul və vaxt yandırır.
DEFAULT_RATE_LIMIT_RETRIES = 3      # ilk sorğudan ƏLAVƏ cəhd sayı
DEFAULT_BACKOFF_BASE_S = 2.0        # 2s, 4s, 8s, ...
DEFAULT_BACKOFF_CAP_S = 60.0
#: Jitter payı ≤ %10 — eyni anda oyanan case-ləri dağıdır, amma gözləmə
#: müddətinin ARTAN olmasını pozmur (test bunu yoxlayır).
BACKOFF_JITTER = 0.1


@dataclass
class _StreamState:
    """Bir SSE axışının yığılmış vəziyyəti."""

    text_parts: list[str] = field(default_factory=list)
    # thought-lar eyni `id` ilə bir neçə dəfə gəlir (əvvəl tool, sonra observation) —
    # `id` üzrə üst-üstə yazılır, ilk görünmə sırası saxlanılır.
    thoughts: dict[str, dict[str, Any]] = field(default_factory=dict)
    thought_order: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    retriever: list[dict[str, Any]] = field(default_factory=list)
    event_counts: dict[str, int] = field(default_factory=dict)
    message_id: str = ""
    conversation_id: str = ""
    task_id: str = ""
    saw_message_end: bool = False
    error_code: str = ""
    error_message: str = ""
    #: `error` event-inin öz `status`-u. Upstream statusu (429/529) çox vaxt
    #: BUNDA deyil, mesajın içindədir — hər ikisi təsnifata verilir.
    error_status: int | None = None
    malformed_lines: int = 0
    data_lines: int = 0

    @property
    def text(self) -> str:
        return "".join(self.text_parts)


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
        self.max_rate_limit_retries = _env_num(
            "AGENTPROOF_RATE_LIMIT_RETRIES", max_rate_limit_retries, DEFAULT_RATE_LIMIT_RETRIES
        )
        self.backoff_base_s = float(
            _env_num("AGENTPROOF_BACKOFF_BASE_S", backoff_base_s, DEFAULT_BACKOFF_BASE_S)
        )
        self.backoff_cap_s = float(
            _env_num("AGENTPROOF_BACKOFF_CAP_S", backoff_cap_s, DEFAULT_BACKOFF_CAP_S)
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

        Tək növbəli case-də davranış əvvəlki ilə eynidir (bir sorğu,
        `conversation_id: ""`).
        """
        user_turns = [
            str(m.get("content", ""))
            for m in req.messages
            if m.get("role") == "user" and str(m.get("content", "")).strip()
        ]
        dropped = sum(1 for m in req.messages if m.get("role") not in ("user", None))
        if not user_turns:
            user_turns = [req.query]

        # `user` bütün növbələrdə EYNİ olmalıdır — Dify söhbəti son istifadəçiyə
        # bağlayır. Növbədən növbəyə dəyişsə, zəncir sükutla qırılardı.
        end_user = f"{self.user}-{req.session_id or uuid.uuid4().hex[:8]}"

        turns: list[AgentResponse] = []
        conversation_id = ""
        for index, query in enumerate(user_turns):
            turn = await self._one_turn(req, query, conversation_id, end_user, index)
            turns.append(turn)
            if turn.error:
                # Zəncir qırıldı: qalan növbələri göndərmək YENİ söhbət açardı
                # və nəticə çoxnövbəli kimi görünüb tək-növbəli olardı.
                break
            new_id = str(turn.raw.get("conversation_id") or "")
            if new_id:
                conversation_id = new_id
            elif index + 1 < len(user_turns):
                turn.error = "conversation_not_returned"
                break

        return self._merge(turns, dropped)

    async def _one_turn(
        self,
        req: AgentRequest,
        query: str,
        conversation_id: str,
        end_user: str,
        turn_index: int,
    ) -> AgentResponse:
        """Bir növbə — `rate_limit` halında eksponensial backoff ilə təkrar.

        Təkrar YALNIZ `rate_limit` sinfi üçündür (AP-024). `credit_exhausted`
        və `auth` dərhal qaytarılır: onları yenidən cəhd etmək pul və vaxt
        yandırır və heç vaxt keçmir.

        `latency_ms` UĞURLU cəhdin ölçüsüdür — backoff gözləməsi ora
        qatılmır, yoxsa hədəfin gecikmə profili bizim gözləməmizlə
        çirklənərdi. Gözləmə müddətləri `raw["retry_waits_s"]`-dədir.
        """
        case_id = str(req.metadata.get("case_id", "")) if req.metadata else ""
        if HALT.tripped:
            # Qaçış onsuz da dayanıb — sorğu GÖNDƏRMİRİK (pul və vaxt yanmır).
            return self._halted(turn_index, query, conversation_id)

        waits: list[float] = []
        burned: list[Usage] = []
        attempt = 0
        while True:
            attempt += 1
            turn = await self._send_once(req, query, conversation_id, end_user, turn_index)
            reason = turn.error_class
            if turn.error is None or reason not in RETRYABLE:
                break
            if attempt > self.max_rate_limit_retries:
                # Cəhdlər bitdi: case `skipped` qalır, AMMA səbəb `rate_limit`
                # kimi kodlanır — "completion_request_error" yığınında itmir.
                turn.raw["retry_exhausted"] = True
                break
            # Atılan cəhdin tokenləri PULLA ödənilib — itməməlidir (AP-026).
            if turn.usage is not None:
                burned.append(turn.usage)
            delay = self._backoff_delay(attempt, turn.raw.get("retry_after_s"))
            waits.append(round(delay, 3))
            await asyncio.sleep(delay)

        turn.attempts = attempt
        turn.retry_usage = _sum_usage(burned, self.model)
        if waits:
            turn.raw["retry_waits_s"] = waits
            turn.raw["retry_reason"] = "rate_limit"
            # Atılan cəhdlərin NEÇƏSİNİN tokeni ölçüldü — qalanının xərci
            # NAMƏLUMDUR, sıfır deyil (AP-026).
            turn.raw["measured_retries"] = len(burned)
        turn.raw["attempts"] = attempt
        if turn.error_class in HALTING:
            # Növbəti case-ləri göndərməyin mənası yoxdur: səbəb hədəfdə deyil,
            # hesabdadır. Qaçış BÜTÖVLÜKDƏ dayanır, səbəb adı ilə.
            HALT.trip(turn.error_class or "", _error_detail(turn), case_id)
        return turn

    def _backoff_delay(self, attempt: int, retry_after_s: Any = None) -> float:
        """`Retry-After` varsa ONA hörmət, yoxsa eksponensial artım + jitter."""
        explicit = _opt_float(retry_after_s)
        if explicit is not None and explicit >= 0:
            return min(explicit, self.backoff_cap_s)
        delay = min(self.backoff_base_s * (2 ** (attempt - 1)), self.backoff_cap_s)
        return delay + random.uniform(0.0, delay * BACKOFF_JITTER)

    def _halted(self, turn_index: int, query: str, conversation_id: str) -> AgentResponse:
        """Qaçış dayandırılıb — hədəfə TOXUNMADAN adlandırılmış cavab."""
        reason = HALT.reason or "unknown"
        return AgentResponse(
            text="",
            latency_ms=0,
            attempts=0,
            error=f"halted:{reason}",
            error_class=reason,
            raw={
                "transport": "none",
                "halted": True,
                "halt_reason": reason,
                "halt_detail": HALT.detail,
                "halt_first_case": HALT.case_id,
                "hint": REASON_HINT.get(reason, ""),
                "request_sent": False,
                "turn_index": turn_index,
                "sent_conversation_id": conversation_id,
                "query": query,
            },
        )

    async def _send_once(
        self,
        req: AgentRequest,
        query: str,
        conversation_id: str,
        end_user: str,
        turn_index: int,
    ) -> AgentResponse:
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
        state = _StreamState()
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
                        return self._http_error(
                            raw,
                            r.status_code,
                            started,
                            turn_index,
                            retry_after=r.headers.get("Retry-After"),
                        )
                    async for line in r.aiter_lines():
                        _consume_line(state, line)
        except httpx.TimeoutException:
            transport_error = "stream_timeout"
        except httpx.RemoteProtocolError:
            # axın yarımçıq kəsildi (chunk bitmədən bağlantı bağlandı)
            transport_error = "stream_incomplete"
        except httpx.HTTPError:
            transport_error = "stream_transport"

        latency_ms = int((time.perf_counter() - started) * 1000)
        turn = self._finish(state, transport_error, latency_ms)
        turn.raw["turn_index"] = turn_index
        turn.raw["sent_conversation_id"] = conversation_id
        turn.raw["query"] = query
        return turn

    def _merge(self, turns: list[AgentResponse], dropped: int) -> AgentResponse:
        """Növbələri BİR cavaba yığır. Semantika `types.AgentResponse.turns`-dədir."""
        last = turns[-1]
        if len(turns) == 1 and not dropped:
            # Tək növbəli case — köhnə davranışın eynisi, heç nə sarılmır.
            return last

        tool_calls: list[ToolCall] = []
        retrieved: list[RetrievedChunk] = []
        seen_chunks: set[str] = set()
        input_tokens = output_tokens = cached_tokens = 0
        model = ""
        for turn in turns:
            tool_calls.extend(turn.tool_calls)
            for chunk in turn.retrieved:
                if chunk.chunk_id and chunk.chunk_id in seen_chunks:
                    continue
                seen_chunks.add(chunk.chunk_id)
                retrieved.append(chunk)
            if turn.usage:
                input_tokens += turn.usage.input_tokens
                output_tokens += turn.usage.output_tokens
                cached_tokens += turn.usage.cached_tokens
                model = turn.usage.model or model

        usage = (
            Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                model=model or self.model,
            )
            if any(t.usage for t in turns)
            else None
        )
        # Atılmış (backoff) cəhdlərin tokenləri də növbələr üzrə toplanır —
        # çoxnövbəli case-də yanan pul tək növbədə gizlənməməlidir (AP-026).
        retry_usage = _sum_usage([t.retry_usage for t in turns if t.retry_usage], self.model)
        conversation_ids = [
            str(t.raw.get("conversation_id") or "") for t in turns
        ]
        return AgentResponse(
            text=last.text,
            tool_calls=tool_calls,
            retrieved=retrieved,
            usage=usage,
            latency_ms=sum(t.latency_ms for t in turns),
            raw={
                "transport": "sse",
                "multi_turn": True,
                "n_turns_sent": len(turns),
                "conversation_id": conversation_ids[0] if conversation_ids else "",
                # Zəncirlənmənin SÜBUTU: bütün növbələr eyni söhbətdədirmi?
                "conversation_ids": conversation_ids,
                "conversation_chained": (
                    len(turns) > 1 and len(set(filter(None, conversation_ids))) == 1
                ),
                "turn_errors": [t.error for t in turns],
                "dropped_scripted_assistant_turns": dropped,
                "message_id": last.raw.get("message_id", ""),
                "attempts": sum(t.attempts for t in turns),
                "measured_retries": sum(
                    int(t.raw.get("measured_retries", 0) or 0) for t in turns
                ),
            },
            error=next((t.error for t in turns if t.error), None),
            # Zənciri qıran İLK xətanın sinfi — sonrakılar onun nəticəsidir.
            error_class=next((t.error_class for t in turns if t.error), None),
            attempts=sum(t.attempts for t in turns),
            retry_usage=retry_usage,
            turns=turns,
        )

    # ------------------------------------------------------------------ daxili
    def _http_error(
        self,
        raw: bytes,
        status: int,
        started: float,
        turn_index: int = 0,
        retry_after: str | None = None,
    ) -> AgentResponse:
        body = _json_or_text(raw)
        code = str(body.get("code", f"http_{status}"))
        message = str(body.get("message", ""))
        return AgentResponse(
            text="",
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw={
                **body,
                "turn_index": turn_index,
                "http_status": status,
                # Səbəb sinfi köhnə artefaktlarda da hesablana bilsin deyə xam
                # zərf `dify_error` formatında saxlanılır.
                "dify_error": {"code": code, "message": message, "status": status},
                # `Retry-After` başlığı: hədəf nə qədər gözləməyi ÖZÜ deyirsə,
                # bizim eksponensial təxminimiz yox, ONUN rəqəmi tətbiq olunur.
                "retry_after_s": _opt_float(retry_after),
            },
            error=code if code in DIFY_INFRA_ERRORS else f"unexpected:{code}",
            error_class=classify_failure(code=code, message=message, status=status),
        )

    def _finish(self, state: _StreamState, transport_error: str, latency_ms: int) -> AgentResponse:
        text = state.text
        error = _classify(state, transport_error)
        # SƏBƏB SİNFİ: kod tək başına bəs etmir. `completion_request_error`
        # altında həm 429 (gözlə), həm "credit balance too low" (gözləmə,
        # balans doldur) gəlirdi — fərqi yalnız mesaj göstərir (AP-024).
        error_class = (
            classify_failure(
                code=state.error_code or error or "",
                message=state.error_message,
                status=state.error_status,
            )
            if error
            else None
        )
        return AgentResponse(
            text=text,
            tool_calls=_tool_calls(state),
            retrieved=[_chunk(rr) for rr in state.retriever],
            usage=_usage(state.usage, self.model),
            latency_ms=latency_ms,
            raw={
                "transport": "sse",
                "message_id": state.message_id,
                "conversation_id": state.conversation_id,
                "task_id": state.task_id,
                "sse_event_counts": dict(state.event_counts),
                "sse_data_lines": state.data_lines,
                "sse_malformed_lines": state.malformed_lines,
                "saw_message_end": state.saw_message_end,
                # Dify öz xərc hesabını da verir — bizim qiymət cədvəlimizlə
                # fərqlənə bilər, ona görə XAM halda saxlanılır (müqayisə üçün).
                "dify_usage": dict(state.usage),
                "dify_error": (
                    {
                        "code": state.error_code,
                        "message": state.error_message,
                        "status": state.error_status,
                    }
                    if state.error_code
                    else None
                ),
                "n_retriever_resources": len(state.retriever),
            },
            error=error,
            error_class=error_class,
        )


# ---------------------------------------------------------------- SSE parsinqi
def _consume_line(state: _StreamState, line: str) -> None:
    """Bir SSE sətri. `data:` olmayan sətirlər (ping, boş, `event:`) atılır."""
    stripped = line.strip()
    if not stripped or not stripped.startswith("data:"):
        return
    payload = stripped[len("data:") :].strip()
    if not payload or payload == "[DONE]":
        return
    state.data_lines += 1
    try:
        event = json.loads(payload)
    except ValueError:
        state.malformed_lines += 1
        return
    if not isinstance(event, dict):
        state.malformed_lines += 1
        return
    _consume_event(state, event)


def _consume_event(state: _StreamState, event: dict[str, Any]) -> None:
    kind = str(event.get("event", ""))
    state.event_counts[kind] = state.event_counts.get(kind, 0) + 1

    for key, attr in (("message_id", "message_id"), ("conversation_id", "conversation_id"),
                      ("task_id", "task_id")):
        value = event.get(key)
        if value and not getattr(state, attr):
            setattr(state, attr, str(value))

    if kind in TEXT_EVENTS:
        state.text_parts.append(str(event.get("answer", "")))
    elif kind == "message_replace":
        # Dify moderasiya nəticəsində bütün cavabı əvəz edir
        state.text_parts = [str(event.get("answer", ""))]
    elif kind == "agent_thought":
        _consume_thought(state, event)
    elif kind == "message_end":
        state.saw_message_end = True
        meta = event.get("metadata") or {}
        if isinstance(meta, dict):
            usage = meta.get("usage")
            if isinstance(usage, dict):
                state.usage = usage
            resources = meta.get("retriever_resources")
            if isinstance(resources, list):
                state.retriever = [r for r in resources if isinstance(r, dict)]
    elif kind == "error":
        state.error_code = str(event.get("code", "") or f"http_{event.get('status', '')}")
        state.error_message = str(event.get("message", ""))
        state.error_status = _opt_int(event.get("status"))
    # ping / message_file / tts_message / workflow_* — sayılır, atılır


def _consume_thought(state: _StreamState, event: dict[str, Any]) -> None:
    """`agent_thought` eyni `id` ilə təkrar gəlir; sonuncu versiya saxlanılır."""
    thought_id = str(event.get("id") or f"pos-{event.get('position', len(state.thoughts))}")
    if thought_id not in state.thoughts:
        state.thought_order.append(thought_id)
        state.thoughts[thought_id] = {}
    current = state.thoughts[thought_id]
    for key in ("tool", "tool_input", "observation", "thought", "position"):
        value = event.get(key)
        # boş dəyər dolu dəyəri üzməməlidir (dispatch event-i observation-suz gəlir)
        if value not in (None, "", {}) or key not in current:
            current[key] = value


def _tool_calls(state: _StreamState) -> list[ToolCall]:
    """Tool çağırışlarının çağırılma ARDICILLIĞI (`tool_call_matches` üçün).

    Bir `agent_thought` bir neçə tool daşıya bilər: `tool` sahəsi `;` ilə
    birləşdirilir, `tool_input` və `observation` isə tool adına görə açarlanır.
    Bilik bazası retrieval tool-u (`dataset_<uuid>`) da bura düşür — real
    ardıcıllığı gizlətmirik.
    """
    calls: list[ToolCall] = []
    for thought_id in state.thought_order:
        thought = state.thoughts[thought_id]
        raw_names = str(thought.get("tool") or "")
        if not raw_names.strip():
            continue
        args_map = _as_dict(thought.get("tool_input"))
        obs_map = _as_dict(thought.get("observation"))
        names = [n.strip() for n in raw_names.split(TOOL_SEPARATOR) if n.strip()]
        for name in names:
            arguments = _pick(name, args_map, len(names))
            calls.append(
                ToolCall(
                    name=name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                    result=_pick(name, obs_map, len(names)),
                )
            )
    return calls


def _as_dict(value: Any) -> dict[str, Any]:
    parsed = _maybe_json(value)
    return parsed if isinstance(parsed, dict) else {}


def _pick(name: str, mapping: dict[str, Any], n_tools: int) -> Any:
    """Dify `tool_input`/`observation`-u tool adına görə açarlayır:
    `{"lookup_order": {...}}`. Tək tool-luq thought-da açarsız (birbaşa)
    format da qəbul edilir."""
    if not mapping:
        return None
    if name in mapping:
        return _maybe_json(mapping[name])
    return mapping if n_tools == 1 else None


def _chunk(rr: dict[str, Any]) -> RetrievedChunk:
    return RetrievedChunk(
        # Dify identifikator kimi `segment_id` verir (UUID) — korpusdakı
        # `sənəd#bənd` lövbərləri deyil. Bax: hesabatdakı məhdudiyyət qeydi.
        chunk_id=str(rr.get("segment_id") or rr.get("document_id") or ""),
        text=str(rr.get("content", "")),
        score=_as_float(rr.get("score")),
        document=str(rr.get("document_name", "")),
    )


def _classify(state: _StreamState, transport_error: str) -> str | None:
    """Xəta adlandırılır — səssiz boş cavab qaytarılmır."""
    if state.error_code:
        code = state.error_code
        return code if code in DIFY_INFRA_ERRORS else f"unexpected:{code}"
    if not state.saw_message_end:
        if transport_error:
            return transport_error
        if state.data_lines and state.data_lines == state.malformed_lines:
            return "stream_unreadable"
        return "stream_incomplete"
    if not state.text.strip():
        # `message_end` gəldi, amma bir dənə də mətn parçası yoxdur
        return "empty_answer"
    return None


def _json_or_text(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return {"code": "invalid_response", "message": raw.decode("utf-8", errors="replace")[:500]}
    return data if isinstance(data, dict) else {"data": data}


def _maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value


def _as_float(value: Any) -> float | None:
    """Dify SSE-də `score` STRING gəlir ("0.7879...")."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _opt_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _opt_float(value: Any) -> float | None:
    """`Retry-After` saniyə ilə gəlir; HTTP-date formatı DƏSTƏKLƏNMİR.

    Tanınmayan dəyər `None` qaytarır — yəni eksponensial backoff-a düşürük.
    Səhv parse edilmiş tarixi "0 saniyə" kimi oxumaq rate limit-i daha da
    pisləşdirərdi.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _env_num(name: str, explicit: Any, default: Any) -> Any:
    """Konfiqurasiya sırası: birbaşa arqument > mühit dəyişəni > default."""
    if explicit is not None:
        return explicit
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return type(default)(float(raw))
    except (TypeError, ValueError):
        return default


def _sum_usage(items: list[Usage | None], model: str = "") -> Usage | None:
    """Bir neçə `Usage`-ı toplayır. Boş siyahı -> `None` (sıfır DEYİL, yoxdur)."""
    present = [u for u in items if u is not None]
    if not present:
        return None
    return Usage(
        input_tokens=sum(u.input_tokens for u in present),
        output_tokens=sum(u.output_tokens for u in present),
        cached_tokens=sum(u.cached_tokens for u in present),
        model=next((u.model for u in present if u.model), model),
    )


def _error_detail(response: AgentResponse) -> str:
    """Xətanın insan üçün oxunan izahı (hesabatda səbəb kimi görünür)."""
    dify_error = (response.raw or {}).get("dify_error") or {}
    message = str(dify_error.get("message", "")).strip()
    code = str(dify_error.get("code", "") or response.error or "")
    return f"{code}: {message}"[:500] if message else code


def _usage(u: dict[str, Any] | None, model: str) -> Usage | None:
    if not u:
        return None
    return Usage(
        input_tokens=_as_int(u.get("prompt_tokens", 0)),
        output_tokens=_as_int(u.get("completion_tokens", 0)),
        # Dify usage-da model adı YOXDUR — etiket adapter konfiqurasiyasından.
        model=model or str(u.get("model", "")),
    )


@register_adapter("dify_http")
def dify_http(**config: Any) -> DifyHttpAgent:
    return DifyHttpAgent(**config)

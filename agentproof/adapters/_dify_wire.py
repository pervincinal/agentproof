"""Dify SSE MƏFTİL (wire) formatı — axın baytlarından `AgentResponse`-a.

Burada YALNIZ Dify-ə xas olan yaşayır: event adları, `agent_thought`-un
təkrarlanan `id`-si, `;` ilə birləşən tool adları, `dify_error` zərfi, xəta
kodları. Nə HTTP, nə backoff, nə söhbət zənciri — onlar `http_agent.py` və
`_http_core.py`-dədir (AP-029).

Sərhəd belə oxunur: Dify sabah event adını dəyişsə, DƏYİŞƏN FAYL BUDUR.

Axından çıxarılanlar:
  agent_message / message  -> yekun cavab mətni (parça-parça gəlir)
  agent_thought            -> tool çağırışlarının ARDICILLIĞI (`tool_call_matches`)
  message_end.metadata.usage               -> token + xərc (`cost_under`)
  message_end.metadata.retriever_resources -> retrieval (`retrieval_hit_at_k`)
  error                    -> hədəfin öz xəta zərfi

Səssiz boş cavab YOXDUR: yarımçıq axın, timeout, transport xətası və boş cavab —
hamısı `AgentResponse.error` sahəsində ADLA görünür.

`error` NƏ baş verdiyini deyir, `error_class` isə NƏ ETMƏLİ olduğunu
(`agentproof/failure.py`). `full-run-03`-də 25 case eyni `completion_request_error`
kodu altında `skipped` oldu, halbuki 24-ü "credit balance is too low" (gözləməklə
KEÇMİR), qalanı 429/529 (gözləməklə KEÇİR) idi. Təsnifatı BU fayl edir, qərarı
(gözlə / dayan) nüvə verir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentproof.adapters._http_core import (
    as_float,
    as_int,
    json_or_text,
    maybe_json,
    opt_float,
    opt_int,
    sse_data,
)
from agentproof.failure import classify_failure
from agentproof.types import AgentResponse, RetrievedChunk, ToolCall, Usage

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

TRANSPORT = "sse"


@dataclass
class StreamState:
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


# ---------------------------------------------------------------- SSE parsinqi
def consume_line(state: StreamState, line: str) -> None:
    """Bir SSE sətri. Çərçivə sətirləri (ping, boş, `event:`, `[DONE]`) atılır."""
    payload = sse_data(line)
    if payload is None:
        return
    state.data_lines += 1
    event = maybe_json(payload)
    if not isinstance(event, dict):
        state.malformed_lines += 1
        return
    _consume_event(state, event)


def _consume_event(state: StreamState, event: dict[str, Any]) -> None:
    kind = str(event.get("event", ""))
    state.event_counts[kind] = state.event_counts.get(kind, 0) + 1

    for key in ("message_id", "conversation_id", "task_id"):
        value = event.get(key)
        if value and not getattr(state, key):
            setattr(state, key, str(value))

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
        state.error_status = opt_int(event.get("status"))
    # ping / message_file / tts_message / workflow_* — sayılır, atılır


def _consume_thought(state: StreamState, event: dict[str, Any]) -> None:
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


# --------------------------------------------------------------- çıxarış qatı
def _tool_calls(state: StreamState) -> list[ToolCall]:
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
    parsed = maybe_json(value)
    return parsed if isinstance(parsed, dict) else {}


def _pick(name: str, mapping: dict[str, Any], n_tools: int) -> Any:
    """Dify `tool_input`/`observation`-u tool adına görə açarlayır:
    `{"lookup_order": {...}}`. Tək tool-luq thought-da açarsız (birbaşa)
    format da qəbul edilir."""
    if not mapping:
        return None
    if name in mapping:
        return maybe_json(mapping[name])
    return mapping if n_tools == 1 else None


def _chunk(rr: dict[str, Any]) -> RetrievedChunk:
    return RetrievedChunk(
        # Dify identifikator kimi `segment_id` verir (UUID) — korpusdakı
        # `sənəd#bənd` lövbərləri deyil. Bax: hesabatdakı məhdudiyyət qeydi.
        chunk_id=str(rr.get("segment_id") or rr.get("document_id") or ""),
        text=str(rr.get("content", "")),
        score=as_float(rr.get("score")),
        document=str(rr.get("document_name", "")),
    )


def _usage(u: dict[str, Any] | None, model: str) -> Usage | None:
    if not u:
        return None
    return Usage(
        input_tokens=as_int(u.get("prompt_tokens", 0)),
        output_tokens=as_int(u.get("completion_tokens", 0)),
        # Dify usage-da model adı YOXDUR — etiket adapter konfiqurasiyasından.
        model=model or str(u.get("model", "")),
    )


def _classify(state: StreamState, transport_error: str) -> str | None:
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


# ------------------------------------------------------------ cavab qurucusu
def response_from_stream(
    state: StreamState, transport_error: str, latency_ms: int, model: str
) -> AgentResponse:
    """Yığılmış axın -> `AgentResponse` (bir növbə)."""
    error = _classify(state, transport_error)
    # SƏBƏB SİNFİ: kod tək başına bəs etmir. `completion_request_error` altında
    # həm 429 (gözlə), həm "credit balance too low" (gözləmə, balans doldur)
    # gəlirdi — fərqi yalnız mesaj göstərir (AP-024).
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
        text=state.text,
        tool_calls=_tool_calls(state),
        retrieved=[_chunk(rr) for rr in state.retriever],
        usage=_usage(state.usage, model),
        latency_ms=latency_ms,
        raw={
            "transport": TRANSPORT,
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


def response_from_http_error(
    raw: bytes,
    status: int,
    latency_ms: int,
    turn_index: int = 0,
    retry_after: str | None = None,
) -> AgentResponse:
    """200 olmayan cavab — Dify xəta zərfi (axın ümumiyyətlə başlamadı)."""
    body = json_or_text(raw)
    code = str(body.get("code", f"http_{status}"))
    message = str(body.get("message", ""))
    return AgentResponse(
        text="",
        latency_ms=latency_ms,
        raw={
            **body,
            "turn_index": turn_index,
            "http_status": status,
            # Səbəb sinfi köhnə artefaktlarda da hesablana bilsin deyə xam zərf
            # `dify_error` formatında saxlanılır.
            "dify_error": {"code": code, "message": message, "status": status},
            # `Retry-After` başlığı: hədəf nə qədər gözləməyi ÖZÜ deyirsə, bizim
            # eksponensial təxminimiz yox, ONUN rəqəmi tətbiq olunur.
            "retry_after_s": opt_float(retry_after),
        },
        error=code if code in DIFY_INFRA_ERRORS else f"unexpected:{code}",
        error_class=classify_failure(code=code, message=message, status=status),
    )


def error_detail(response: AgentResponse) -> str:
    """Xətanın insan üçün oxunan izahı — Dify zərfindən (hesabatda səbəb)."""
    dify_error = (response.raw or {}).get("dify_error") or {}
    message = str(dify_error.get("message", "")).strip()
    code = str(dify_error.get("code", "") or response.error or "")
    return f"{code}: {message}"[:500] if message else code

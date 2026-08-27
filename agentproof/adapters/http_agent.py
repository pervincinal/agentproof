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

import json
import os
import time
import uuid
from dataclasses import dataclass, field
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
                        return self._http_error(raw, r.status_code, started, turn_index)
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
            },
            error=next((t.error for t in turns if t.error), None),
            turns=turns,
        )

    # ------------------------------------------------------------------ daxili
    def _http_error(
        self, raw: bytes, status: int, started: float, turn_index: int = 0
    ) -> AgentResponse:
        body = _json_or_text(raw)
        code = str(body.get("code", f"http_{status}"))
        return AgentResponse(
            text="",
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw={**body, "turn_index": turn_index},
            error=code if code in DIFY_INFRA_ERRORS else f"unexpected:{code}",
        )

    def _finish(self, state: _StreamState, transport_error: str, latency_ms: int) -> AgentResponse:
        text = state.text
        error = _classify(state, transport_error)
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
                    {"code": state.error_code, "message": state.error_message}
                    if state.error_code
                    else None
                ),
                "n_retriever_resources": len(state.retriever),
            },
            error=error,
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

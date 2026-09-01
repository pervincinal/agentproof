"""In-process (callable) adapter — şəbəkəsiz hədəflər üçün (AP-031).

LangGraph, LlamaIndex və ya müştərinin öz sinfi auditə HTTP endpoint VERMİR:
ölçüləcək şey elə bu Python prosesinin içindəki obyektdir. İndiyə qədər
şəbəkəsiz yeganə adapter `mock_agent.py` idi, o isə REAL ÇAĞIRIŞ ETMİR —
skriptləşdirilmiş lüğətdir. Yəni in-process hədəfi ölçmək üçün müştəri öz
sistemini HTTP-yə bükməyə məcbur idi: auditə əlavə gün və müqavimət.

    adapter = create_adapter("callable", fn=my_graph.answer)

ÇAĞIRIŞ MÜQAVİLƏSİ (`fn` sync və ya async)
------------------------------------------
    fn(query)                      # söhbətsiz hədəf
    fn(query, conversation_id)     # söhbəti ÖZÜ idarə edən hədəf

Hansının işlədiyi `inspect.signature` ilə müəyyən olunur (`multi_turn=` ilə
ƏLLƏ də verilir). İkinci forma yoxdursa hədəf çoxnövbəli case-i ölçmür və bunu
DEYİR (`multi_turn_unsupported`) — növbələri ayrı-ayrı çağırışlarla göndərib
"çoxnövbəli ölçdük" demək yalan olardı.

`fn` nə qaytara bilər: `AgentResponse` (olduğu kimi), `str` (yalnız mətn) və
ya `dict` (`_field_map.FieldMap` ilə oxunur). `map_response` verilibsə əvvəlcə
o çağırılır. Nümunə: `docs/ADAPTERS.md`.

BACKOFF BURADA TƏTBİQ OLUNMUR — SƏBƏBİ İLƏ
------------------------------------------
`RetryPolicy(max_retries=0)` QƏSDƏNdir, unutqanlıq deyil: (a) gözləməklə keçən
nəqliyyat 429-u yoxdur, çağırış prosesin içindədir; (b) `fn`-in idempotent
olduğunu bilmirik — qraf artıq tool işlədibsə təkrar onu İKİNCİ dəfə edərdi;
(c) agent daxilən model API-sinə çıxırsa təkrar ONUN işidir, bizimki onun
üstünə gələrdi (2×3 = 6 çağırış, 6× xərc).

Nüvə yenə də işlədilir: `HALT` hörmət olunur (daxili kreditlər bitibsə qaçış
bütövlükdə dayanır), təsnifat və növbə birləşməsi eynidir. `rate_limit`
görünsə cəhdlər dərhal tükənmiş sayılır, səbəb isə ADI ilə qalır. Uyğunluq
boşluğu `test_adapter_conformance.CALLABLE_GAP`-də kilidlənib.
"""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from typing import Any, Callable

from agentproof.adapters._field_map import FieldMap, build_response, error_detail
from agentproof.adapters._http_core import (
    RetryPolicy,
    merge_turns,
    multi_turn_unsupported_response,
    run_conversation,
    send_with_retry,
    user_turns,
)
from agentproof.adapters.base import register_adapter
from agentproof.failure import classify_failure
from agentproof.types import UNKNOWN, AgentRequest, AgentResponse

TRANSPORT = "in_process"

#: `fn` söhbət id-sini bu adlı parametrlə qəbul edir.
CONVERSATION_KW = "conversation_id"

#: `fn` istisna atdı — cavab BUNUNLA adlanır (`unexpected:` prefiksi kimi).
EXCEPTION_PREFIX = "callable_exception"


def accepts_conversation(fn: Callable[..., Any]) -> bool:
    """`fn` söhbət id-si qəbul edirmi — TƏXMİN deyil, imza faktı.

    İmza oxuna bilməyən çağırılanlar (C funksiyaları, bəzi partial-lar) üçün
    cavab `False`-dur: bilmədiyimiz halda "dəstəkləyir" demək çoxnövbəli
    case-ləri gizlicə tək-növbəliyə çevirərdi.
    """
    try:
        parameters = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return False
    kinds = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters):
        return True
    if any(p.name == CONVERSATION_KW for p in parameters):
        return True
    return len([p for p in parameters if p.kind in kinds]) >= 2


class CallableAgent:
    """Python çağırılanını müqaviləyə uyğunlaşdıran adapter."""

    name = "callable"

    def __init__(
        self,
        fn: Callable[..., Any] | None = None,
        version: str = UNKNOWN,
        model: str | None = None,
        map_response: Callable[[Any], Any] | None = None,
        health_fn: Callable[[], Any] | None = None,
        multi_turn: bool | None = None,
        **paths: Any,
    ) -> None:
        if not callable(fn):
            raise ValueError("callable: `fn` verilməyib (çağırıla bilən obyekt gözlənilir)")
        self.fn = fn
        self.version = version
        self.model = model or ""
        self.map_response = map_response
        self.health_fn = health_fn
        self.multi_turn = accepts_conversation(fn) if multi_turn is None else bool(multi_turn)
        self.map = FieldMap.from_config(**paths)
        #: Şəbəkə yoxdur -> təkrar da yoxdur. Bax modul docstring-i.
        self.retry = RetryPolicy(max_retries=0)

    async def health(self) -> bool:
        """`health_fn` verilməyibsə `fn`-in çağırıla bilməsi yeganə faktdır —
        bu, "hədəf HAZIRDIR" DEMİR (`preflight` fərqi 1-ci sətirdə yazır)."""
        if self.health_fn is None:
            return callable(self.fn)
        try:
            result = self.health_fn()
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        except Exception:
            # `health()` exception ATMIR: atsaydı, qaçış başlanğıcdakı
            # sağlamlıq yoxlamasında stack trace ilə çökərdi.
            return False

    async def invoke(self, req: AgentRequest) -> AgentResponse:
        queries, dropped = user_turns(req.messages, req.query)
        if len(queries) > 1 and not self.multi_turn:
            return multi_turn_unsupported_response(
                len(queries),
                detail=(
                    f"callable: `fn` `{CONVERSATION_KW}` qəbul etmir — söhbət "
                    "zəncirlənə bilmir, çoxnövbəli case ölçülmür"
                ),
                transport=TRANSPORT,
            )
        # Şəbəkəsiz hədəfdə söhbət açarını BİZ veririk: qarşı tərəfdə id
        # paylayan server yoxdur. Açar bütün növbələr üçün EYNİDİR — nüvənin
        # zəncir maşını (`run_conversation`) onu cavabdan geri oxuyur, yəni
        # növbə xəta versə qalan növbələr yenə GÖNDƏRİLMİR.
        conversation = f"case-{req.session_id or uuid.uuid4().hex[:8]}"
        case_id = str(req.metadata.get("case_id", "")) if req.metadata else ""

        async def turn(query: str, _chained: str, index: int) -> AgentResponse:
            return await send_with_retry(
                lambda: self._call_once(query, conversation, index),
                policy=self.retry,
                model=self.model,
                case_id=case_id,
                detail=error_detail,
                context={"turn_index": index, "conversation_id": conversation, "query": query},
            )

        turns = await run_conversation(turn, queries)
        return merge_turns(turns, dropped, model=self.model, transport=TRANSPORT)

    async def _call_once(self, query: str, conversation_id: str, index: int) -> AgentResponse:
        """BİR çağırış. Gecikməni ADAPTER ölçür (wall-clock)."""
        started = time.perf_counter()
        try:
            result = await self._invoke_fn(query, conversation_id)
        except Exception as exc:  # hədəfin öz xətası — qaçışı sındırmır
            turn = _exception_response(exc, int((time.perf_counter() - started) * 1000))
        else:
            latency_ms = int((time.perf_counter() - started) * 1000)
            turn = self._to_response(result, latency_ms)
        turn.raw["turn_index"] = index
        turn.raw["sent_conversation_id"] = conversation_id
        turn.raw["query"] = query
        # Hədəf öz id-sini qaytarıbsa ONA hörmət; qaytarmayıbsa bizimki qalır.
        if not turn.raw.get("conversation_id"):
            turn.raw["conversation_id"] = conversation_id
        return turn

    async def _invoke_fn(self, query: str, conversation_id: str) -> Any:
        """Sync çağırılan AYRI THREAD-də qaçır.

        Sinxron `fn`-i birbaşa çağırsaq, o, event loop-u bloklayardı və
        paralel lane-lər (`--max-connections`) növbəyə düzülərdi: ölçülən
        gecikmə hədəfin deyil, bizim növbəmizin gecikməsi olardı.
        """
        args = (query, conversation_id) if self.multi_turn else (query,)
        if inspect.iscoroutinefunction(self.fn):
            return await self.fn(*args)
        result = await asyncio.to_thread(self.fn, *args)
        # `fn` sync olub awaitable qaytara bilər (məs. `graph.ainvoke` sarğısı).
        return await result if inspect.isawaitable(result) else result

    def _to_response(self, result: Any, latency_ms: int) -> AgentResponse:
        if self.map_response is not None:
            result = self.map_response(result)
        if isinstance(result, AgentResponse):
            # Hədəf bütöv cavabı özü qurub: yalnız ölçdüyümüz gecikmə və
            # nəqliyyat etiketi əlavə olunur, sahələrinə TOXUNULMUR.
            if not result.latency_ms:
                result.latency_ms = latency_ms
            result.raw.setdefault("transport", TRANSPORT)
            if result.error is None and not result.text.strip():
                result.error = "empty_answer"
                result.error_class = classify_failure(code="empty_answer")
            return result
        text_only = isinstance(result, str)
        payload = {"text": result} if text_only else result
        fmap = FieldMap(text=("text",)) if text_only else self.map
        return build_response(payload, fmap, latency_ms=latency_ms,
                              model=self.model, transport=TRANSPORT)


def _exception_response(exc: Exception, latency_ms: int) -> AgentResponse:
    """İstisna ADLANDIRILIR və TƏSNİF OLUNUR — qaçış sınmır.

    Mesaj təsnifata verilir, çünki in-process agent daxilən model API-sinə
    çıxır: "Your credit balance is too low" mətni `credit_exhausted` deməkdir
    və qaçış dayanmalıdır. Mətn tanınmasa sinif `unknown` qalır — təxmin
    etmirik.
    """
    kind = type(exc).__name__
    message = str(exc)
    status = _exception_status(exc)
    return AgentResponse(
        text="",
        latency_ms=latency_ms,
        raw={"transport": TRANSPORT, "exception_type": kind,
             "target_error": {"code": kind, "message": message[:2000], "status": status}},
        error=f"{EXCEPTION_PREFIX}:{kind}",
        error_class=classify_failure(code=kind, message=message, status=status),
    )


def _exception_status(exc: Exception) -> int | None:
    """SDK istisnaları statusu ÖZLƏRİ daşıyır (`status_code` / `response
    .status_code`) — 429-u mesaj naxışından təxmin etmirik."""
    candidates = (getattr(exc, "status_code", None), getattr(exc, "status", None),
                  getattr(getattr(exc, "response", None), "status_code", None))
    return next(
        (v for v in candidates if isinstance(v, int) and not isinstance(v, bool)), None
    )



@register_adapter("callable")
def callable_agent(**config: Any) -> CallableAgent:
    return CallableAgent(**config)

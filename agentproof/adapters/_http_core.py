"""HTTP hədəflər üçün adapter NÜVƏSİ — Dify-dən asılı DEYİL (AP-029).

`http_agent.py` 786 sətir idi və içində üç ayrı qat yaşayırdı:

  (a) Dify SSE wire formatı — `agent_message` / `agent_thought`, `dify_error`,
      `TOOL_SEPARATOR`;
  (b) backoff/təkrar maşını (AP-024) və yanan tokenlərin yığımı (AP-026);
  (c) çoxnövbəli söhbət zənciri və növbələrin birləşdirilməsi.

(b) və (c) Dify-yə XAS DEYİL: hər HTTP/söhbət hədəfi üçün eynidir. Onlar
adapterin içində qalsaydı, ikinci adapter yazılanda sıfırdan təkrarlanardı —
və hər təkrarda fərqli sınardı. `full-run-03`-ün dərsləri (kredit xətası ilə
rate limit-in fərqi, atılan cəhdin tokeni, çoxnövbəli case-in tək-növbəli kimi
ölçülməsi) BİR yerdə saxlanılır.

Nüvə wire formatı haqqında YALNIZ İKİ şey bilir və hər ikisi `AgentResponse`
müqaviləsindədir:

  * `response.error_class` — `failure.py` səbəb sinfi (təsnifatı adapter edir);
  * `response.raw["conversation_id"]` — növbələri zəncirləyən söhbət açarı.

Bunlardan başqa nüvə hədəfin protokoluna toxunmur: sorğu göndərmək tamamilə
adapterin `send_once` funksiyasındadır.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Sequence

from agentproof.failure import HALT, HALTING, REASON_HINT, RETRYABLE
from agentproof.types import AgentResponse, ToolCall, Usage, RetrievedChunk

# --- backoff (AP-024) ------------------------------------------------------
# YALNIZ `rate_limit` sinfi üçün. `credit_exhausted` və `auth` yenidən cəhd
# EDİLMİR: onlar gözləməklə keçmir, hər təkrar sadəcə pul və vaxt yandırır.
DEFAULT_RATE_LIMIT_RETRIES = 3      # ilk sorğudan ƏLAVƏ cəhd sayı
DEFAULT_BACKOFF_BASE_S = 2.0        # 2s, 4s, 8s, ...
DEFAULT_BACKOFF_CAP_S = 60.0
#: Jitter payı ≤ %10 — eyni anda oyanan case-ləri dağıdır, amma gözləmə
#: müddətinin ARTAN olmasını pozmur (test bunu yoxlayır).
BACKOFF_JITTER = 0.1

#: Zəncir qurula bilmədikdə verilən ad. Susub yeni söhbətlə davam etmək
#: çoxnövbəli case-i gizlicə tək-növbəliyə çevirmək demək olardı.
MISSING_CONVERSATION_ID = "conversation_not_returned"


# ============================================================ konfiqurasiya
def env_num(name: str, explicit: Any, default: Any) -> Any:
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


@dataclass
class RetryPolicy:
    """`rate_limit` üçün eksponensial backoff. Başqa sinif üçün İŞLƏMİR."""

    max_retries: int = DEFAULT_RATE_LIMIT_RETRIES
    base_s: float = DEFAULT_BACKOFF_BASE_S
    cap_s: float = DEFAULT_BACKOFF_CAP_S

    @staticmethod
    def from_config(
        max_rate_limit_retries: Any = None,
        backoff_base_s: Any = None,
        backoff_cap_s: Any = None,
    ) -> "RetryPolicy":
        """Mühit dəyişənləri açar kimi CLI-a düşmür — burada oxunur."""
        return RetryPolicy(
            max_retries=env_num(
                "AGENTPROOF_RATE_LIMIT_RETRIES", max_rate_limit_retries,
                DEFAULT_RATE_LIMIT_RETRIES,
            ),
            base_s=float(
                env_num("AGENTPROOF_BACKOFF_BASE_S", backoff_base_s, DEFAULT_BACKOFF_BASE_S)
            ),
            cap_s=float(
                env_num("AGENTPROOF_BACKOFF_CAP_S", backoff_cap_s, DEFAULT_BACKOFF_CAP_S)
            ),
        )

    def delay(self, attempt: int, retry_after_s: Any = None) -> float:
        """`Retry-After` varsa ONA hörmət, yoxsa eksponensial artım + jitter."""
        explicit = opt_float(retry_after_s)
        if explicit is not None and explicit >= 0:
            return min(explicit, self.cap_s)
        delay = min(self.base_s * (2 ** (attempt - 1)), self.cap_s)
        return delay + random.uniform(0.0, delay * BACKOFF_JITTER)


# ================================================================ təkrar maşını
def default_error_detail(response: AgentResponse) -> str:
    """Xətanın insan üçün oxunan izahı (hesabatda səbəb kimi görünür)."""
    return str(response.error or "")


def halted_response(context: dict[str, Any] | None = None) -> AgentResponse:
    """Qaçış dayandırılıb — hədəfə TOXUNMADAN adlandırılmış cavab.

    `attempts = 0` QƏSDƏNdir: "sorğu ümumiyyətlə göndərilmədi". `1` yazmaq
    olmayan xərci "ölçülməmiş" kimi göstərərdi (`types.AgentResponse.attempts`).
    """
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
            **(context or {}),
        },
    )


async def send_with_retry(
    send_once: Callable[[], Awaitable[AgentResponse]],
    *,
    policy: RetryPolicy,
    model: str = "",
    case_id: str = "",
    detail: Callable[[AgentResponse], str] = default_error_detail,
    context: dict[str, Any] | None = None,
) -> AgentResponse:
    """Bir sorğu — `rate_limit` halında eksponensial backoff ilə təkrar.

    Təkrar YALNIZ `rate_limit` sinfi üçündür (AP-024). `credit_exhausted` və
    `auth` dərhal qaytarılır: onları yenidən cəhd etmək pul və vaxt yandırır və
    heç vaxt keçmir.

    `latency_ms` UĞURLU cəhdin ölçüsüdür — backoff gözləməsi ora qatılmır,
    yoxsa hədəfin gecikmə profili bizim gözləməmizlə çirklənərdi. Gözləmə
    müddətləri `raw["retry_waits_s"]`-dədir.

    Atılan cəhdlərin tokenləri itmir: `retry_usage`-a yığılır və hesabatda
    `wasted_cost_usd` kimi görünür (AP-026).
    """
    if HALT.tripped:
        # Qaçış onsuz da dayanıb — sorğu GÖNDƏRMİRİK (pul və vaxt yanmır).
        return halted_response(context)

    waits: list[float] = []
    burned: list[Usage] = []
    attempt = 0
    while True:
        attempt += 1
        turn = await send_once()
        if turn.error is None or turn.error_class not in RETRYABLE:
            break
        if attempt > policy.max_retries:
            # Cəhdlər bitdi: case `skipped` qalır, AMMA səbəb `rate_limit`
            # kimi kodlanır — "completion_request_error" yığınında itmir.
            turn.raw["retry_exhausted"] = True
            break
        # Atılan cəhdin tokenləri PULLA ödənilib — itməməlidir (AP-026).
        if turn.usage is not None:
            burned.append(turn.usage)
        delay = policy.delay(attempt, turn.raw.get("retry_after_s"))
        waits.append(round(delay, 3))
        await asyncio.sleep(delay)

    turn.attempts = attempt
    turn.retry_usage = sum_usage(burned, model)
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
        HALT.trip(turn.error_class or "", detail(turn), case_id)
    return turn


# ============================================================ söhbət zənciri
def user_turns(messages: Sequence[dict[str, Any]], fallback: str) -> tuple[list[str], int]:
    """Göndəriləcək istifadəçi növbələri + ATILAN skriptli növbələrin sayı.

    Dataset-də skriptləşdirilmiş `assistant` növbəsi varsa, o GÖNDƏRİLMİR
    (söhbət tarixçəsini hədəf özü qurur; kənardan assistant mesajı yeritmək
    mümkün deyil). Bu, susqun qalmır — say qaytarılır və `raw`-a düşür.
    """
    queries = [
        str(m.get("content", ""))
        for m in messages
        if m.get("role") == "user" and str(m.get("content", "")).strip()
    ]
    dropped = sum(1 for m in messages if m.get("role") not in ("user", None))
    return (queries or [fallback]), dropped


async def run_conversation(
    send_turn: Callable[[str, str, int], Awaitable[AgentResponse]],
    queries: Sequence[str],
) -> list[AgentResponse]:
    """Növbələri BİR söhbətdə ardıcıl göndərir (`conversation_id` zənciri).

    İlk növbə boş id ilə gedir; cavabdan qayıdan `raw["conversation_id"]`
    sonrakı bütün növbələrə yazılır. Bu olmasa hər növbə ayrı söhbət açardı və
    çoxnövbəli case-lər tək-növbəli kimi ölçülərdi (`COVERAGE.md §7`).

    Zəncir qırılarsa qaçış SƏSSİZCƏ davam etmir:
      * bir növbə xəta qaytarsa, qalan növbələr GÖNDƏRİLMİR;
      * ilk növbə id qaytarmasa və daha növbə varsa, `conversation_not_returned`.
    """
    turns: list[AgentResponse] = []
    conversation_id = ""
    for index, query in enumerate(queries):
        turn = await send_turn(query, conversation_id, index)
        turns.append(turn)
        if turn.error:
            # Zəncir qırıldı: qalan növbələri göndərmək YENİ söhbət açardı
            # və nəticə çoxnövbəli kimi görünüb tək-növbəli olardı.
            break
        new_id = str(turn.raw.get("conversation_id") or "")
        if new_id:
            conversation_id = new_id
        elif index + 1 < len(queries):
            turn.error = MISSING_CONVERSATION_ID
            break
    return turns


def merge_turns(
    turns: list[AgentResponse],
    dropped: int,
    *,
    model: str = "",
    transport: str = "",
) -> AgentResponse:
    """Növbələri BİR cavaba yığır. Semantika `types.AgentResponse.turns`-dədir.

      text        -> SONUNCU növbənin mətni (qiymətləndirilən yekun cavab)
      tool_calls  -> BÜTÜN növbələrin birləşməsi, sıra ilə (`forbidden_tools`
                     üçün başqa cür olmaz)
      retrieved   -> bütün növbələrin birləşməsi, `chunk_id` üzrə təkrarsız
      usage       -> növbələrin CƏMİ (xərc bütöv söhbətə görə hesablanır)
      latency_ms  -> növbələrin cəmi
    """
    last = turns[-1]
    if len(turns) == 1 and not dropped:
        # Tək növbəli case — köhnə davranışın eynisi, heç nə sarılmır.
        return last

    tool_calls: list[ToolCall] = []
    retrieved: list[RetrievedChunk] = []
    seen_chunks: set[str] = set()
    input_tokens = output_tokens = cached_tokens = 0
    usage_model = ""
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
            usage_model = turn.usage.model or usage_model

    usage = (
        Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            model=usage_model or model,
        )
        if any(t.usage for t in turns)
        else None
    )
    # Atılmış (backoff) cəhdlərin tokenləri də növbələr üzrə toplanır —
    # çoxnövbəli case-də yanan pul tək növbədə gizlənməməlidir (AP-026).
    retry_usage = sum_usage([t.retry_usage for t in turns if t.retry_usage], model)
    conversation_ids = [str(t.raw.get("conversation_id") or "") for t in turns]
    return AgentResponse(
        text=last.text,
        tool_calls=tool_calls,
        retrieved=retrieved,
        usage=usage,
        latency_ms=sum(t.latency_ms for t in turns),
        raw={
            "transport": transport,
            "multi_turn": True,
            "n_turns_sent": len(turns),
            "conversation_id": conversation_ids[0] if conversation_ids else "",
            # Zəncirlənmənin SÜBUTU: bütün növbələr eyni söhbətdədirmi?
            "conversation_chained": (
                len(turns) > 1 and len(set(filter(None, conversation_ids))) == 1
            ),
            "conversation_ids": conversation_ids,
            "turn_errors": [t.error for t in turns],
            "dropped_scripted_assistant_turns": dropped,
            "message_id": last.raw.get("message_id", ""),
            "attempts": sum(t.attempts for t in turns),
            "measured_retries": sum(int(t.raw.get("measured_retries", 0) or 0) for t in turns),
        },
        error=next((t.error for t in turns if t.error), None),
        # Zənciri qıran İLK xətanın sinfi — sonrakılar onun nəticəsidir.
        error_class=next((t.error_class for t in turns if t.error), None),
        attempts=sum(t.attempts for t in turns),
        retry_usage=retry_usage,
        turns=turns,
    )


# ================================================================== köməkçilər
def sum_usage(items: Sequence[Usage | None], model: str = "") -> Usage | None:
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


def json_or_text(raw: bytes) -> dict[str, Any]:
    """Xəta gövdəsi JSON deyilsə də ADLANDIRILIR — susqun atılmır."""
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return {"code": "invalid_response", "message": raw.decode("utf-8", errors="replace")[:500]}
    return data if isinstance(data, dict) else {"data": data}


def maybe_json(value: Any) -> Any:
    """String JSON daşıyırsa açır; daşımırsa olduğu kimi qaytarır."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value


def as_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def opt_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    """Rəqəm STRING kimi gələ bilər ("0.7879...") — SSE-də adi haldır."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def opt_float(value: Any) -> float | None:
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


def sse_data(line: str) -> str | None:
    """SSE sətrindən faydalı yükü çıxarır (protokol qatı, hədəfdən asılı deyil).

    `data:` olmayan sətirlər (ping, boş sətir, `event:`) və `[DONE]` üçün
    `None` — bunlar məzmun deyil, çərçivədir.
    """
    stripped = line.strip()
    if not stripped.startswith("data:"):
        return None
    payload = stripped[len("data:") :].strip()
    return payload or None if payload != "[DONE]" else None

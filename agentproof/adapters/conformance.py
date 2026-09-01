"""Adapter uyğunluq (conformance) dəsti — müqavilə SƏNƏDDƏN KODA (AP-028).

`base.py`-dəki `AgentAdapter` Protocol cəmi dörd üzv tələb edir
(`name` / `version` / `invoke` / `health`). Müqavilənin ƏSL şərtləri isə həmin
faylın docstring-ində MƏTN kimi yaşayırdı və yalnız `test_http_adapter.py`-də,
üstəlik Dify-yə XAS formada yoxlanırdı. İkinci adapter yazılan an pozuntu
yalnız canlı qaçışda — yəni müştərinin pulu ilə — üzə çıxardı.

Bu modul həmin şərtləri icra olunan yoxlamalara çevirir. Dəst adapterin
DAXİLİNİ tanımır: yalnız `invoke()` / `health()` çağırır və qayıdan
`AgentResponse`-a baxır.

NECƏ QOŞULUR
------------
Yeni adapter üçün `ConformanceTarget` alt sinfi yazılır (~30 sətir): adapteri
qurur, adı çəkilən ssenarini hədəfdə HAZIRLAYIR və hədəfə neçə sorğu getdiyini
sayır. Sonra `agentproof/tests/test_adapter_conformance.py`-dəki siyahıya
əlavə olunur — bütün dəst avtomatik qaçır.

    class MyTarget(ConformanceTarget):
        label = "my_adapter"
        supports = frozenset({OK, EMPTY, ...})
        def adapter(self): ...
        def arrange(self, scenario): ...   # -> AgentRequest
        def requests_sent(self): ...

DƏSTƏKLƏNMƏYƏN SSENARİ SƏSSİZ KEÇMİR
------------------------------------
`supports` çatmayanda yoxlama ADI ilə `skip` olunur, üstəlik
`test_adapter_conformance.py` hər hədəfin dəstək matrisini AYRICA kilidləyir:
bir adapter sabah bir ssenarini "dəstəkləmir" elan edərsə, matris testi sınır.
Beləcə boşluq həmişə görünür — nə susqun yaşıl, nə susqun sarı.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from agentproof.adapters.base import AgentAdapter
from agentproof.failure import (
    AUTH,
    BAD_REQUEST,
    CREDIT_EXHAUSTED,
    HALT,
    HALTING,
    RATE_LIMIT,
    REASONS,
    RETRYABLE,
)
from agentproof.types import AgentRequest, AgentResponse, RetrievedChunk, ToolCall, Usage

# ============================================================== ssenarilər
#: Normal cavab: mətn + `usage` + retrieval + bir tool çağırışı.
OK = "ok"
#: Hədəf qəsdən yavaş cavab verir — `latency_ms`-in ADAPTER tərəfindən
#: doldurulduğunu yoxlamaq üçün.
SLOW = "slow"
#: Cavab gəlir, amma hədəf token istifadəsini VERMİR.
NO_USAGE = "no_usage"
#: Cavab gəlir, retrieval YOXDUR (boş siyahı, `None` deyil).
NO_RETRIEVAL = "no_retrieval"
#: Hədəf boş cavab qaytarır — bu, SƏSSİZ keçməməlidir.
EMPTY = "empty"
#: Hədəf əvvəl rate limit, sonra normal cavab verir (backoff sonra UĞUR).
RATE_LIMIT_THEN_OK = "rate_limit_then_ok"
#: Hədəf davamlı rate limit qaytarır (cəhdlər tükənir).
RATE_LIMIT_ALWAYS = "rate_limit_always"
#: Rate limit-dən əvvəl tokenlər YANDI — atılan cəhdin `usage`-ı gəlir.
RATE_LIMIT_BURNS_TOKENS = "rate_limit_burns_tokens"
#: `auth` sinfi — gözləməklə keçmir, təkrar YOXDUR.
AUTH_ERROR = "auth_error"
#: `bad_request` sinfi — təkrar YOXDUR.
BAD_REQUEST_ERROR = "bad_request_error"
#: `credit_exhausted` sinfi — təkrar YOXDUR.
CREDIT_ERROR = "credit_error"
#: Bir case-də bir neçə istifadəçi növbəsi; ORTA növbədə tool çağırışı.
MULTI_TURN = "multi_turn"

#: Ssenari deyil, QABİLİYYƏT: hədəf əlçatmaz olanda adapter nüsxəsi qurula bilir.
UNREACHABLE = "unreachable"
#: Qabiliyyət: `HALTING` sinfi bütün qaçışı dayandırır (AP-024).
HALTS_RUN = "halts_run"

SCENARIOS: tuple[str, ...] = (
    OK,
    SLOW,
    NO_USAGE,
    NO_RETRIEVAL,
    EMPTY,
    RATE_LIMIT_THEN_OK,
    RATE_LIMIT_ALWAYS,
    RATE_LIMIT_BURNS_TOKENS,
    AUTH_ERROR,
    BAD_REQUEST_ERROR,
    CREDIT_ERROR,
    MULTI_TURN,
)

CAPABILITIES: tuple[str, ...] = SCENARIOS + (UNREACHABLE, HALTS_RUN)

#: `SLOW` ssenarisində hədəfin gözlətdiyi vaxt (ms).
SLOW_MS = 120
#: `RATE_LIMIT_THEN_OK` / `RATE_LIMIT_BURNS_TOKENS`: hədəf neçə dəfə 429 verir.
RATE_LIMIT_TIMES = 2
#: `MULTI_TURN` ssenarisinin növbələri. Sifariş nömrəsi QƏSDƏN yalnız İLK
#: növbədədir: son cavab onu yalnız KONTEKSTdən bilə bilər.
MULTI_TURN_ORDER_ID = "ORD-10015"
#: Orta növbədə (1-dən sayılır: 2-ci) gözlənilən tool çağırışı.
MULTI_TURN_TOOL = "initiate_return"
MULTI_TURN_TURN_WITH_TOOL = 2
MULTI_TURN_N = 3


# ============================================================ hədəf körpüsü
class ConformanceTarget:
    """Adapteri uyğunluq dəstinə qoşan körpü.

    Dəst adapterin daxilini tanımır — hədəfi hazırlamağı və sorğu saymağı
    bilən yeganə yer BURADIR.
    """

    #: pytest id-si.
    label: str = ""
    #: Bu hədəfin hazırlaya bildiyi ssenarilər / qabiliyyətlər.
    supports: frozenset[str] = frozenset(CAPABILITIES)
    #: Adapterin `rate_limit` üçün İLK sorğudan ƏLAVƏ cəhd sayı.
    max_rate_limit_retries: int = 3

    def adapter(self) -> AgentAdapter:
        """Sınanacaq adapter nüsxəsi (backoff test saatı ilə)."""
        raise NotImplementedError

    def arrange(self, scenario: str) -> AgentRequest:
        """Hədəfi ssenariyə hazırlayır və ona uyğun sorğunu qaytarır."""
        raise NotImplementedError

    def requests_sent(self) -> int:
        """Hədəfə indiyədək NEÇƏ sorğu getdi (kumulyativ)."""
        raise NotImplementedError

    def unreachable_adapter(self) -> AgentAdapter:
        """Əlçatmaz hədəfə baxan adapter (`UNREACHABLE` qabiliyyəti)."""
        raise NotImplementedError

    # --- həyat dövrü (default: heç nə) ---------------------------------
    def start(self) -> "ConformanceTarget":
        return self

    def stop(self) -> None:
        return None

    def __enter__(self) -> "ConformanceTarget":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


# ================================================================ köməkçilər
def _shape_errors(r: Any) -> list[str]:
    """`AgentResponse`-un SAHƏ TİPLƏRİ — artefakt sxemi bunlardan asılıdır."""
    bad: list[str] = []
    if not isinstance(r, AgentResponse):
        return [f"invoke() `AgentResponse` qaytarmadı: {type(r).__name__}"]
    if not isinstance(r.text, str):
        bad.append(f"text: {type(r.text).__name__} (str olmalıdır)")
    if not isinstance(r.tool_calls, list) or not all(
        isinstance(t, ToolCall) for t in r.tool_calls
    ):
        bad.append("tool_calls: list[ToolCall] olmalıdır")
    if not isinstance(r.retrieved, list) or not all(
        isinstance(c, RetrievedChunk) for c in r.retrieved
    ):
        bad.append("retrieved: list[RetrievedChunk] olmalıdır")
    if r.usage is not None and not isinstance(r.usage, Usage):
        bad.append("usage: Usage | None olmalıdır")
    if not isinstance(r.latency_ms, int) or isinstance(r.latency_ms, bool):
        bad.append("latency_ms: int olmalıdır")
    if not isinstance(r.raw, dict):
        bad.append("raw: dict olmalıdır")
    if r.error is not None and not isinstance(r.error, str):
        bad.append("error: str | None olmalıdır")
    if r.error_class is not None and not isinstance(r.error_class, str):
        bad.append("error_class: str | None olmalıdır")
    if not isinstance(r.attempts, int) or isinstance(r.attempts, bool):
        bad.append("attempts: int olmalıdır")
    if not isinstance(r.turns, list):
        bad.append("turns: list[AgentResponse] olmalıdır")
    return bad


def _assert_error_pairing(r: AgentResponse, where: str) -> None:
    """`error` NƏ baş verdiyini deyir, `error_class` NƏ ETMƏLİ olduğunu.

    Sinif xətasız görünə BİLMƏZ, xəta isə təsnif olunmadan qala bilməz —
    əks halda hesabatda "səbəbsiz uğursuzluq" sətri yaranır.
    """
    if r.error is None:
        assert r.error_class is None, (
            f"{where}: xəta yoxdur, amma error_class={r.error_class!r} qaldı"
        )
        return
    assert r.error_class in REASONS, (
        f"{where}: error={r.error!r} üçün error_class={r.error_class!r} — "
        f"failure.py sinifləri: {REASONS}"
    )


# =================================================================== YOXLAMALAR
async def _check_invoke_returns_a_typed_response(t: ConformanceTarget) -> None:
    response = await t.adapter().invoke(t.arrange(OK))
    bad = _shape_errors(response)
    assert not bad, "AgentResponse müqaviləsi pozuldu:\n  " + "\n  ".join(bad)
    assert response.text.strip(), "uğurlu ssenaridə mətn boş qalmamalıdır"
    assert response.error is None, response.error


async def _check_response_survives_the_artifact_round_trip(t: ConformanceTarget) -> None:
    """Cavab JSON artefaktına yazılır — `raw` daxil olmaqla serialize olunmalıdır.

    Adapter `raw`-a serialize olunmayan obyekt qoysa (məs. datetime, bytes),
    qaçış GRADER-dən SONRA, artefakt yazılarkən sınardı: yəni bütün pul
    xərclənəndən sonra.
    """
    response = await t.adapter().invoke(t.arrange(OK))
    encoded = json.dumps(response.to_dict(), ensure_ascii=False)
    revived = AgentResponse.from_dict(json.loads(encoded))
    assert revived.text == response.text
    assert revived.latency_ms == response.latency_ms
    assert [c.name for c in revived.tool_calls] == [c.name for c in response.tool_calls]
    assert [c.chunk_id for c in revived.retrieved] == [c.chunk_id for c in response.retrieved]
    assert (revived.usage is None) == (response.usage is None)


async def _check_adapter_declares_name_and_version(t: ConformanceTarget) -> None:
    adapter = t.adapter()
    assert isinstance(adapter, AgentAdapter), "AgentAdapter Protocol-una uyğun deyil"
    assert isinstance(adapter.name, str) and adapter.name, "adapter adsızdır"
    assert isinstance(adapter.version, str) and adapter.version, (
        "version boşdur — artefaktda hədəf versiyası itər (`target_version`)"
    )


async def _check_latency_is_filled_by_the_adapter(t: ConformanceTarget) -> None:
    """`latency_ms`-i adapter ölçür — çağıran tərəf deyil (STACK.md §8.2)."""
    response = await t.adapter().invoke(t.arrange(SLOW))
    assert isinstance(response.latency_ms, int)
    assert response.latency_ms >= SLOW_MS // 2, (
        f"hədəf ~{SLOW_MS} ms gözlətdi, adapter isə {response.latency_ms} ms yazdı — "
        "gecikmə ölçülmür"
    )


async def _check_usage_missing_means_none_not_zero(t: ConformanceTarget) -> None:
    """Token gəlmirsə `usage = None`. SIFIR yazmaq "ölçdük, xərc yoxdur" deməkdir."""
    response = await t.adapter().invoke(t.arrange(NO_USAGE))
    assert response.usage is None, (
        f"usage={response.usage!r} — ölçülməyən istifadə sıfır kimi göstərilib"
    )


async def _check_cost_grader_skips_when_usage_is_missing(t: ConformanceTarget) -> None:
    """`usage=None`-un NƏTİCƏSİ: `cost_under` `skipped` verir, uğur DEYİL.

    Müqavilənin bu şərti yalnız nəticəsi ilə mənalıdır — ona görə burada
    grader-in özü ilə yoxlanılır.
    """
    from agentproof.graders import registry
    from agentproof.types import Case

    response = await t.adapter().invoke(t.arrange(NO_USAGE))
    case = Case(id="conformance-cost", input="x", grader="cost_under",
                expect={"max_cost_usd": 1.0})
    result = registry.get("cost_under").grade(case, response)
    assert result.skipped, f"`usage` yoxdur, amma grader qərar verdi: {result.reason}"
    assert not result.passed


async def _check_retrieved_is_an_empty_list_never_none(t: ConformanceTarget) -> None:
    """Retrieval olmayanda BOŞ SİYAHI — `None` deyil.

    `retrieval_hit_at_k` "sahə yoxdur" ilə "axtardı, tapmadı" arasında fərq
    qoymalıdır; siyahının özü həmişə var.
    """
    response = await t.adapter().invoke(t.arrange(NO_RETRIEVAL))
    assert response.retrieved == [], f"retrieved={response.retrieved!r}"


async def _check_retrieved_chunks_are_typed(t: ConformanceTarget) -> None:
    response = await t.adapter().invoke(t.arrange(OK))
    assert response.retrieved, "OK ssenarisi retrieval qaytarmalıdır (test boş yaşıl olmasın)"
    for chunk in response.retrieved:
        assert isinstance(chunk, RetrievedChunk)
        assert isinstance(chunk.chunk_id, str) and chunk.chunk_id
        assert chunk.score is None or isinstance(chunk.score, float), (
            f"score float | None olmalıdır: {chunk.score!r}"
        )


async def _check_empty_answer_is_named_not_silent(t: ConformanceTarget) -> None:
    """Səssiz boş cavab QADAĞANDIR: boş mətn xəta ADI ilə görünməlidir.

    Adlanmasa, grader onu "yanlış cavab" kimi sayardı və hesabat hədəfi
    işləməyən infrastruktura görə cəzalandırardı.
    """
    response = await t.adapter().invoke(t.arrange(EMPTY))
    assert response.text.strip() == ""
    assert response.error, "boş cavab səssiz keçdi — `error` doldurulmalıdır"
    _assert_error_pairing(response, "empty")


async def _check_success_carries_no_error_class(t: ConformanceTarget) -> None:
    response = await t.adapter().invoke(t.arrange(OK))
    assert response.error is None and response.error_class is None


async def _check_attempts_counts_the_single_request(t: ConformanceTarget) -> None:
    """`attempts` göndərilən sorğu sayıdır — uğurlu tək cəhddə 1."""
    before = t.requests_sent()
    response = await t.adapter().invoke(t.arrange(OK))
    assert t.requests_sent() - before == 1
    assert response.attempts == 1, f"attempts={response.attempts}"


async def _check_single_turn_leaves_turns_empty(t: ConformanceTarget) -> None:
    """Tək növbəli case sarınmır — `turns` boş, `n_turns` 1."""
    response = await t.adapter().invoke(t.arrange(OK))
    assert response.turns == []
    assert response.n_turns == 1
    assert response.turn_texts == [response.text]


# --- retry müqaviləsi (AP-024) ---------------------------------------------
async def _no_retry(t: ConformanceTarget, scenario: str, expected_class: str) -> None:
    HALT.reset()
    before = t.requests_sent()
    response = await t.adapter().invoke(t.arrange(scenario))
    sent = t.requests_sent() - before
    assert response.error, f"{scenario}: xəta gözlənilirdi"
    assert response.error_class == expected_class, (
        f"{scenario}: error_class={response.error_class!r}, gözlənilən {expected_class!r}"
    )
    assert expected_class not in RETRYABLE
    assert sent == 1, f"{scenario}: {sent} sorğu getdi — təkrar EDİLMƏMƏLİDİR"
    assert response.attempts == 1, f"{scenario}: attempts={response.attempts}"
    assert "retry_waits_s" not in response.raw
    HALT.reset()


async def _check_auth_error_is_not_retried(t: ConformanceTarget) -> None:
    await _no_retry(t, AUTH_ERROR, AUTH)


async def _check_bad_request_is_not_retried(t: ConformanceTarget) -> None:
    await _no_retry(t, BAD_REQUEST_ERROR, BAD_REQUEST)


async def _check_credit_exhausted_is_not_retried(t: ConformanceTarget) -> None:
    await _no_retry(t, CREDIT_ERROR, CREDIT_EXHAUSTED)


async def _check_rate_limit_is_retried_with_growing_backoff(t: ConformanceTarget) -> None:
    """YEGANƏ təkrarlanan sinif. Hədəf özünə gələndə case UĞUR qazanır."""
    before = t.requests_sent()
    response = await t.adapter().invoke(t.arrange(RATE_LIMIT_THEN_OK))
    sent = t.requests_sent() - before

    assert response.error is None, f"hədəf özünə gəldi, cavab isə: {response.error!r}"
    assert sent == RATE_LIMIT_TIMES + 1, f"{sent} sorğu getdi"
    assert response.attempts == RATE_LIMIT_TIMES + 1
    waits = response.raw.get("retry_waits_s")
    assert waits and len(waits) == RATE_LIMIT_TIMES, f"retry_waits_s={waits!r}"
    assert all(b > a for a, b in zip(waits, waits[1:])), f"backoff artmır: {waits}"
    assert response.raw.get("retry_reason") == RATE_LIMIT


async def _check_exhausted_rate_limit_stays_named(t: ConformanceTarget) -> None:
    """Cəhdlər bitsə də səbəb ADI ilə qalır — ümumi xəta yığınında itmir."""
    before = t.requests_sent()
    response = await t.adapter().invoke(t.arrange(RATE_LIMIT_ALWAYS))
    sent = t.requests_sent() - before

    assert response.error, "cəhdlər bitdi, amma cavab xətasız göründü"
    assert response.error_class == RATE_LIMIT
    assert response.raw.get("retry_exhausted") is True
    assert sent == t.max_rate_limit_retries + 1, f"{sent} sorğu getdi"
    assert response.attempts == t.max_rate_limit_retries + 1


async def _check_burned_retry_tokens_are_not_lost(t: ConformanceTarget) -> None:
    """Atılan cəhdin tokenləri PULLA ödənilib — `retry_usage`-da qalır (AP-026)."""
    response = await t.adapter().invoke(t.arrange(RATE_LIMIT_BURNS_TOKENS))
    assert response.error is None
    assert response.retry_usage is not None, (
        "atılan cəhdlərin `usage`-ı gəldi, amma `retry_usage` boşdur — yanan pul itdi"
    )
    assert response.retry_usage.input_tokens > 0
    # `retry_usage` UĞURLU cavabın `usage`-ına QATILMIR: biri ölçmənin özüdür,
    # digəri yanan puldur (`wasted_cost_usd`).
    assert response.usage is not None
    assert response.raw.get("measured_retries", 0) >= 1


async def _check_halting_class_stops_the_whole_run(t: ConformanceTarget) -> None:
    """`credit_exhausted` növbəti case-lərə sorğu GÖNDƏRTMİR (AP-024)."""
    HALT.reset()
    try:
        adapter = t.adapter()
        first = await adapter.invoke(t.arrange(CREDIT_ERROR))
        assert first.error_class in HALTING
        assert HALT.tripped and HALT.reason in HALTING

        sent = t.requests_sent()
        later = await adapter.invoke(t.arrange(OK))
        assert t.requests_sent() == sent, "qaçış dayanıb, amma sorğu getdi"
        assert later.error and later.error.startswith("halted:")
        assert later.raw.get("request_sent") is False
        assert later.attempts == 0, "göndərilməyən sorğu cəhd kimi sayılmamalıdır"
    finally:
        HALT.reset()


# --- çoxnövbəli müqavilə ---------------------------------------------------
async def _check_multi_turn_records_every_turn(t: ConformanceTarget) -> None:
    response = await t.adapter().invoke(t.arrange(MULTI_TURN))
    assert response.error is None, response.error
    assert response.n_turns == MULTI_TURN_N
    assert len(response.turns) == MULTI_TURN_N
    assert len(response.turn_texts) == MULTI_TURN_N
    assert all(_shape_errors(turn) == [] for turn in response.turns)
    assert response.text == response.turns[-1].text, (
        "yekun mətn SONUNCU növbənin mətnidir (qiymətləndirilən cavab odur)"
    )


async def _check_multi_turn_tool_calls_are_the_union(t: ConformanceTarget) -> None:
    """`tool_calls` BÜTÜN növbələrin birləşməsidir.

    Yalnız son növbəyə baxsaydıq, 2-ci növbədəki qadağan olunmuş çağırış
    (`forbidden_tools`) səssizcə KEÇƏRDİ — ən zərərli rejim ölçülməmiş qalardı.
    """
    response = await t.adapter().invoke(t.arrange(MULTI_TURN))
    per_turn = [c.name for turn in response.turns for c in turn.tool_calls]
    assert [c.name for c in response.tool_calls] == per_turn
    assert MULTI_TURN_TOOL in per_turn, "ssenari orta növbədə tool çağırmalıdır"
    assert [c.name for c in response.turns[-1].tool_calls] == [], (
        "test boş yaşıl olmasın: tool son növbədə DEYİL"
    )


async def _check_multi_turn_usage_and_latency_are_summed(t: ConformanceTarget) -> None:
    """Xərc və gecikmə BÜTÖV söhbətə görədir, yalnız son növbəyə görə yox."""
    response = await t.adapter().invoke(t.arrange(MULTI_TURN))
    assert response.latency_ms == sum(turn.latency_ms for turn in response.turns)
    assert response.usage is not None
    assert response.usage.input_tokens == sum(
        turn.usage.input_tokens for turn in response.turns if turn.usage
    )
    assert response.usage.output_tokens == sum(
        turn.usage.output_tokens for turn in response.turns if turn.usage
    )


async def _check_multi_turn_keeps_context(t: ConformanceTarget) -> None:
    """Növbələr BİR söhbətdədir: son cavab yalnız kontekstdən bilə biləcəyi
    sifariş nömrəsini bilməlidir. Zəncir qırılsaydı, 15 çoxnövbəli case
    tək-növbəli kimi ölçülərdi (`COVERAGE.md §7`)."""
    response = await t.adapter().invoke(t.arrange(MULTI_TURN))
    assert MULTI_TURN_ORDER_ID in response.text, response.text


# --- health ----------------------------------------------------------------
async def _check_health_is_false_when_target_is_unreachable(t: ConformanceTarget) -> None:
    """Hədəf əlçatmazdırsa `health()` `False` qaytarır — exception ATMIR.

    Exception atsaydı, qaçış başlanğıcdakı sağlamlıq yoxlamasında stack
    trace ilə çökərdi və səbəb "adapter xarabdır" kimi oxunardı.
    """
    result = await t.unreachable_adapter().health()
    assert result is False, f"health()={result!r}"


async def _check_health_is_true_for_a_live_target(t: ConformanceTarget) -> None:
    assert await t.adapter().health() is True


# ================================================================== reyestr
@dataclass(frozen=True)
class Check:
    """Bir müqavilə şərti."""

    name: str
    why: str
    needs: tuple[str, ...]
    run: Callable[[ConformanceTarget], Awaitable[None]]

    def missing(self, target: ConformanceTarget) -> tuple[str, ...]:
        return tuple(n for n in self.needs if n not in target.supports)


CONTRACT: tuple[Check, ...] = (
    Check(
        "invoke_returns_a_typed_response",
        "invoke() `AgentResponse` qaytarır və bütün sahələr sxem tipindədir",
        (OK,),
        _check_invoke_returns_a_typed_response,
    ),
    Check(
        "response_survives_the_artifact_round_trip",
        "cavab (`raw` daxil) JSON artefaktına yazılıb geri oxuna bilir",
        (OK,),
        _check_response_survives_the_artifact_round_trip,
    ),
    Check(
        "adapter_declares_name_and_version",
        "adapter `name`/`version` verir — hesabatda hədəf kimliyi görünür",
        (),
        _check_adapter_declares_name_and_version,
    ),
    Check(
        "latency_is_filled_by_the_adapter",
        "`latency_ms`-i ADAPTER ölçür (wall-clock), çağıran tərəf deyil",
        (SLOW,),
        _check_latency_is_filled_by_the_adapter,
    ),
    Check(
        "usage_missing_means_none_not_zero",
        "hədəf token verməsə `usage = None` — sıfır DEYİL",
        (NO_USAGE,),
        _check_usage_missing_means_none_not_zero,
    ),
    Check(
        "cost_grader_skips_when_usage_is_missing",
        "`usage=None` -> `cost_under` `skipped` verir, səssiz keçmir",
        (NO_USAGE,),
        _check_cost_grader_skips_when_usage_is_missing,
    ),
    Check(
        "retrieved_is_an_empty_list_never_none",
        "retrieval yoxdursa boş siyahı — `None` deyil",
        (NO_RETRIEVAL,),
        _check_retrieved_is_an_empty_list_never_none,
    ),
    Check(
        "retrieved_chunks_are_typed",
        "`retrieved[]` elementləri `RetrievedChunk` (id str, score float|None)",
        (OK,),
        _check_retrieved_chunks_are_typed,
    ),
    Check(
        "empty_answer_is_named_not_silent",
        "boş cavab `error` ilə işarələnir — səssiz keçmir",
        (EMPTY,),
        _check_empty_answer_is_named_not_silent,
    ),
    Check(
        "success_carries_no_error_class",
        "xəta yoxdursa `error_class` da yoxdur (səbəbsiz uğursuzluq sətri olmasın)",
        (OK,),
        _check_success_carries_no_error_class,
    ),
    Check(
        "attempts_counts_the_single_request",
        "`attempts` göndərilən sorğu sayıdır (uğurlu tək cəhddə 1)",
        (OK,),
        _check_attempts_counts_the_single_request,
    ),
    Check(
        "single_turn_leaves_turns_empty",
        "tək növbəli case sarınmır: `turns` boş, `n_turns` 1",
        (OK,),
        _check_single_turn_leaves_turns_empty,
    ),
    Check(
        "auth_error_is_not_retried",
        "`auth` gözləməklə keçmir -> DƏRHAL qayıdır, təkrar yoxdur",
        (AUTH_ERROR,),
        _check_auth_error_is_not_retried,
    ),
    Check(
        "bad_request_is_not_retried",
        "`bad_request` gözləməklə keçmir -> DƏRHAL qayıdır",
        (BAD_REQUEST_ERROR,),
        _check_bad_request_is_not_retried,
    ),
    Check(
        "credit_exhausted_is_not_retried",
        "`credit_exhausted` gözləməklə keçmir -> DƏRHAL qayıdır",
        (CREDIT_ERROR,),
        _check_credit_exhausted_is_not_retried,
    ),
    Check(
        "rate_limit_is_retried_with_growing_backoff",
        "YEGANƏ təkrarlanan sinif; gözləmə müddəti artır, sonra UĞUR",
        (RATE_LIMIT_THEN_OK,),
        _check_rate_limit_is_retried_with_growing_backoff,
    ),
    Check(
        "exhausted_rate_limit_stays_named",
        "cəhdlər bitsə də səbəb `rate_limit` kimi kodlanır",
        (RATE_LIMIT_ALWAYS,),
        _check_exhausted_rate_limit_stays_named,
    ),
    Check(
        "burned_retry_tokens_are_not_lost",
        "atılan cəhdin tokenləri `retry_usage`-da qalır (AP-026)",
        (RATE_LIMIT_BURNS_TOKENS,),
        _check_burned_retry_tokens_are_not_lost,
    ),
    Check(
        "halting_class_stops_the_whole_run",
        "`credit_exhausted` sonrakı case-lərə sorğu göndərtmir",
        (CREDIT_ERROR, OK, HALTS_RUN),
        _check_halting_class_stops_the_whole_run,
    ),
    Check(
        "multi_turn_records_every_turn",
        "`turns` hər növbənin öz cavabını saxlayır; yekun mətn SONUNCUdur",
        (MULTI_TURN,),
        _check_multi_turn_records_every_turn,
    ),
    Check(
        "multi_turn_tool_calls_are_the_union",
        "`tool_calls` BÜTÜN növbələrin birləşməsidir, sıra ilə",
        (MULTI_TURN,),
        _check_multi_turn_tool_calls_are_the_union,
    ),
    Check(
        "multi_turn_usage_and_latency_are_summed",
        "xərc və gecikmə bütöv söhbətə görə toplanır",
        (MULTI_TURN,),
        _check_multi_turn_usage_and_latency_are_summed,
    ),
    Check(
        "multi_turn_keeps_context",
        "növbələr bir söhbətdədir — son cavab əvvəlki növbəni xatırlayır",
        (MULTI_TURN,),
        _check_multi_turn_keeps_context,
    ),
    Check(
        "health_is_true_for_a_live_target",
        "işlək hədəfdə `health()` `True`",
        (),
        _check_health_is_true_for_a_live_target,
    ),
    Check(
        "health_is_false_when_target_is_unreachable",
        "əlçatmaz hədəfdə `health()` `False` qaytarır, exception ATMIR",
        (UNREACHABLE,),
        _check_health_is_false_when_target_is_unreachable,
    ),
)

#: `test_adapter_conformance.py` bunu parametrləşdirmə üçün işlədir.
CHECK_NAMES: tuple[str, ...] = tuple(c.name for c in CONTRACT)


def checks_for(target: ConformanceTarget) -> tuple[Check, ...]:
    """Verilmiş hədəfdə HƏQİQƏTƏN qaça bilən yoxlamalar."""
    return tuple(c for c in CONTRACT if not c.missing(target))

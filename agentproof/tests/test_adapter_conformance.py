"""AP-028 — uyğunluq dəsti DÖRD adapterə qoşulur.

    `dify_http`   SSE məftili (Dify Agent Chat)          — 25 keçdi
    `json_http`   bloklayıcı `POST -> JSON` (AP-030)     — 25 keçdi
    `callable`    in-process Python obyekti (AP-031)     — 23 keçdi, 2 ADLI skip
    `mock`        skriptləşdirilmiş lüğət                — 16 keçdi, 9 ADLI skip

`agentproof/adapters/conformance.py` müqavilənin ÖZÜDÜR (adapterdən asılı
deyil). Bu fayl yalnız KÖRPÜLƏRİ saxlayır: hər hədəf üçün ~40 sətir — adapteri
qurur, adı çəkilən ssenarini hazırlayır, sorğu sayır.

Növbəti adapter gələndə bura növbəti körpü yazılır və 25 yoxlamanın hamısı
avtomatik qaçır. Müqavilə docstring-də deyil, burada yaşayır.

Fayl ÜÇ şeyi sübut edir:
  1. hər iki adapter müqavilənin dəstəklədiyi hissəsini KEÇİR;
  2. dəstəklənməyən hissə ADI ilə sayılır (matris testi) — susqun boşluq yoxdur;
  3. dəst BOŞ YAŞIL DEYİL: qəsdən pozulmuş adapter həmin yoxlamalarda SINIR.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentproof.adapters import create_adapter
from agentproof.adapters.conformance import (
    AUTH_ERROR,
    BAD_REQUEST_ERROR,
    CAPABILITIES,
    CONTRACT,
    CREDIT_ERROR,
    EMPTY,
    HALTS_RUN,
    MULTI_TURN,
    MULTI_TURN_N,
    MULTI_TURN_ORDER_ID,
    MULTI_TURN_TOOL,
    MULTI_TURN_TURN_WITH_TOOL,
    NO_RETRIEVAL,
    NO_USAGE,
    OK,
    RATE_LIMIT_ALWAYS,
    RATE_LIMIT_BURNS_TOKENS,
    RATE_LIMIT_THEN_OK,
    RATE_LIMIT_TIMES,
    SLOW,
    SLOW_MS,
    UNREACHABLE,
    ConformanceTarget,
)
from agentproof.testing.fake_graph import GRAPH_MAP, FakeSupportGraph
from agentproof.testing.mock_dify import (
    CREDIT_EXHAUSTED_MESSAGE,
    RATE_LIMIT_MESSAGE,
    MockDifyServer,
)
from agentproof.testing.mock_json_agent import (
    CUSTOM_CONVERSATION_PATH,
    CUSTOM_MAP,
    MockJsonAgentServer,
)
from agentproof.types import AgentRequest, AgentResponse, RetrievedChunk, ToolCall, Usage

# Hər ssenarinin ÖZ açar sözü var ki, bir stub-da yan-yana yaşasınlar.
NEEDLE = {
    OK: "cnf-ok",
    SLOW: "cnf-slow",
    NO_USAGE: "cnf-nousage",
    NO_RETRIEVAL: "cnf-noretrieval",
    EMPTY: "cnf-empty",
    RATE_LIMIT_THEN_OK: "cnf-rate-then-ok",
    RATE_LIMIT_ALWAYS: "cnf-rate-always",
    RATE_LIMIT_BURNS_TOKENS: "cnf-rate-burn",
    AUTH_ERROR: "cnf-auth",
    BAD_REQUEST_ERROR: "cnf-badreq",
    CREDIT_ERROR: "cnf-credit",
    MULTI_TURN: "cnf-mt",
}

OK_CHUNK = {
    "chunk_id": "returns-and-refunds#restocking",
    "document": "returns-and-refunds.md",
    "content": "Opened items are subject to a 15% restocking fee.",
    "score": 0.93,
}
OK_TOOL = {"name": "lookup_order", "arguments": {"order_id": "ORD-1042"}, "result": {"ok": True}}
OK_USAGE = {"prompt_tokens": 1820, "completion_tokens": 190}


def _one(scenario: str) -> AgentRequest:
    return AgentRequest(
        messages=[{"role": "user", "content": f"{NEEDLE[scenario]} sualı"}],
        session_id=f"conformance-{scenario}",
        metadata={"case_id": f"conformance-{scenario}"},
    )


# ===================================================== körpü 1: `dify_http`
def _multi_turn_script() -> dict[str, Any]:
    """Yaddaşı OLAN hədəf: cavabı `conversation_id` üzrə tarixçəyə görə verir.

    Dify-ın özü də belə işləyir. Sifariş nömrəsi yalnız İLK növbədədir — son
    cavab onu ancaq zəncir qurulubsa bilə bilər.
    """
    history: dict[str, list[str]] = {}

    def reply(body: dict[str, Any]) -> dict[str, Any]:
        conv = str(body.get("conversation_id") or "")
        query = str(body.get("query", ""))
        turns = history.setdefault(conv, []) if conv else []
        turns.append(query)
        known = next((t.split("ORD-")[1][:5] for t in turns if "ORD-" in t), None)
        if "çatdırıldı" in query:
            answer = (
                f"ORD-{known} 2026-08-20-də çatdırılıb."
                if known
                else "Hansı sifarişi nəzərdə tutursunuz?"
            )
        else:
            answer = "Anladım."
        spec: dict[str, Any] = {"answer": answer}
        if len(turns) == MULTI_TURN_TURN_WITH_TOOL:
            spec["tool_calls"] = [
                {
                    "name": MULTI_TURN_TOOL,
                    "arguments": {"order_id": MULTI_TURN_ORDER_ID},
                    "result": {"ok": True},
                }
            ]
        return spec

    return {"side_effect": reply, "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


DIFY_SCRIPTS: dict[str, dict[str, Any]] = {
    OK: {
        "answer": "Açılmış məhsullarda 15% restocking haqqı tutulur.",
        "retrieved": [OK_CHUNK],
        "tool_calls": [OK_TOOL],
        "usage": OK_USAGE,
    },
    SLOW: {"answer": "gec cavab", "delay_ms": SLOW_MS, "usage": OK_USAGE},
    # `message_end` GƏLİR, amma `usage` sahəsi yoxdur (hədəf token vermir).
    NO_USAGE: {"answer": "token hesabı olmayan cavab", "no_usage": True},
    NO_RETRIEVAL: {"answer": "bilik bazasına toxunmayan cavab", "usage": OK_USAGE},
    EMPTY: {"answer": "", "usage": OK_USAGE},
    RATE_LIMIT_THEN_OK: {
        "error": ("too_many_requests", RATE_LIMIT_MESSAGE, 429),
        "times": RATE_LIMIT_TIMES,
        "answer": "nəhayət cavab",
        "usage": OK_USAGE,
    },
    RATE_LIMIT_ALWAYS: {"error": ("too_many_requests", RATE_LIMIT_MESSAGE, 429)},
    RATE_LIMIT_BURNS_TOKENS: {
        # `message_end` GƏLDİ (tokenlər yandı), sonra axın 429 ilə bitdi.
        "error_event": ("completion_request_error", RATE_LIMIT_MESSAGE, 400),
        "usage_before_error": True,
        "times": RATE_LIMIT_TIMES,
        "answer": "nəhayət cavab",
        "usage": {"prompt_tokens": 800, "completion_tokens": 30},
    },
    AUTH_ERROR: {"error_event": ("provider_not_initialize", "model provider yoxdur", 400)},
    BAD_REQUEST_ERROR: {"error_event": ("invalid_param", "sorğu qəbul edilmədi", 400)},
    CREDIT_ERROR: {"error_event": ("completion_request_error", CREDIT_EXHAUSTED_MESSAGE, 400)},
}


class DifyHttpTarget(ConformanceTarget):
    """`dify_http` + `agentproof.testing.mock_dify` (real HTTP/SSE wire formatı)."""

    label = "dify_http"
    supports = frozenset(CAPABILITIES)
    max_rate_limit_retries = 2

    def __init__(self) -> None:
        self._server = MockDifyServer()
        self._adapter: Any = None

    def start(self) -> "DifyHttpTarget":
        self._server.start()
        return self

    def stop(self) -> None:
        self._server.stop()

    def adapter(self) -> Any:
        if self._adapter is None:
            self._adapter = create_adapter(
                "dify_http",
                base_url=self._server.base_url,
                api_key=self._server.api_key,
                # test saatı: real qaçışda 2 s
                backoff_base_s=0.01,
                max_rate_limit_retries=self.max_rate_limit_retries,
            )
        return self._adapter

    def unreachable_adapter(self) -> Any:
        # Bağlı port: açar VAR, hədəf YOXDUR — `health()` çökməməlidir.
        return create_adapter("dify_http", base_url="http://127.0.0.1:9/v1", api_key="app-x")

    def requests_sent(self) -> int:
        return len(self._server.request_log)

    def arrange(self, scenario: str) -> AgentRequest:
        if scenario == MULTI_TURN:
            self._server.scripted[NEEDLE[MULTI_TURN]] = _multi_turn_script()
            return AgentRequest(
                messages=_multi_turn_messages(),
                session_id="conformance-multi-turn",
                metadata={"case_id": "conformance-multi-turn"},
            )
        self._server.scripted[NEEDLE[scenario]] = dict(DIFY_SCRIPTS[scenario])
        return _one(scenario)


def _multi_turn_messages() -> list[dict[str, str]]:
    needle = NEEDLE[MULTI_TURN]
    return [
        {"role": "user", "content": f"{needle} sifarişim {MULTI_TURN_ORDER_ID}."},
        {"role": "user", "content": f"{needle} təşəkkür edirəm."},
        # ⚠️ sifariş nömrəsi QƏSDƏN təkrarlanmır
        {"role": "user", "content": f"{needle} nə vaxt çatdırıldı?"},
    ]


assert len(_multi_turn_messages()) == MULTI_TURN_N


# ========================================================== körpü 2: `mock`
#: `mock` in-process-dur: nə təkrarlanacaq nəqliyyat xətası var, nə də
#: zəncirlənəcək söhbət. Bu boşluq aşağıdakı matris testində ADI ilə sayılır.
MOCK_SCRIPTS: dict[str, dict[str, Any]] = {
    OK: {
        "answer": "Açılmış məhsullarda 15% restocking haqqı tutulur.",
        "retrieved": [OK_CHUNK],
        "tool_calls": [OK_TOOL],
        "usage": {"input_tokens": 1820, "output_tokens": 190},
    },
    SLOW: {
        "answer": "gec cavab",
        "delay_ms": SLOW_MS,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    },
    NO_USAGE: {"answer": "token hesabı olmayan cavab"},
    NO_RETRIEVAL: {
        "answer": "bilik bazasına toxunmayan cavab",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    },
    EMPTY: {"answer": ""},
    AUTH_ERROR: {"error": "unauthorized", "error_message": "Access token is invalid"},
    BAD_REQUEST_ERROR: {"error": "invalid_param", "error_message": "user is required"},
    CREDIT_ERROR: {
        "error": "completion_request_error",
        "error_message": CREDIT_EXHAUSTED_MESSAGE,
        "error_status": 400,
    },
}


class MockTarget(ConformanceTarget):
    """`mock` — şəbəkəsiz in-process hədəf."""

    label = "mock"
    supports = frozenset(MOCK_SCRIPTS)

    def __init__(self) -> None:
        self._adapter: Any = None

    def adapter(self) -> Any:
        if self._adapter is None:
            self._adapter = create_adapter(
                "mock", scripted={NEEDLE[s]: dict(v) for s, v in MOCK_SCRIPTS.items()}
            )
        return self._adapter

    def requests_sent(self) -> int:
        return self.adapter().calls

    def arrange(self, scenario: str) -> AgentRequest:
        return _one(scenario)


# ===================================================== körpü 3: `json_http`
#: Stub-un sahə adları (`reply` / `cost` / `trace` / `citations` / `thread`)
#: `FieldMap` default namizədlərinin HEÇ BİRİ ilə üst-üstə düşmür — yəni bu
#: 25 yoxlama sahə XƏRİTƏSİNİN işlədiyini sınayır, təsadüfi uyğunluğu yox.
JSON_SCRIPTS: dict[str, dict[str, Any]] = {
    OK: {
        "answer": "Açılmış məhsullarda 15% restocking haqqı tutulur.",
        "retrieved": [OK_CHUNK],
        "tool_calls": [OK_TOOL],
        "usage": {"input_tokens": 1820, "output_tokens": 190},
    },
    SLOW: {"answer": "gec cavab", "delay_ms": SLOW_MS,
           "usage": {"input_tokens": 10, "output_tokens": 5}},
    # `cost` sahəsi ÜMUMİYYƏTLƏ gəlmir (hədəf token vermir).
    NO_USAGE: {"answer": "token hesabı olmayan cavab"},
    NO_RETRIEVAL: {"answer": "bilik bazasına toxunmayan cavab",
                   "usage": {"input_tokens": 10, "output_tokens": 5}},
    EMPTY: {"answer": "", "usage": {"input_tokens": 10, "output_tokens": 0}},
    RATE_LIMIT_THEN_OK: {
        "error": ("too_many_requests", RATE_LIMIT_MESSAGE, 429),
        "times": RATE_LIMIT_TIMES,
        "answer": "nəhayət cavab",
        "usage": {"input_tokens": 100, "output_tokens": 20},
    },
    RATE_LIMIT_ALWAYS: {"error": ("too_many_requests", RATE_LIMIT_MESSAGE, 429)},
    RATE_LIMIT_BURNS_TOKENS: {
        # 200 statusu, gövdədə HƏM yanmış tokenlər, HƏM xəta zərfi.
        "error_body": ("too_many_requests", RATE_LIMIT_MESSAGE, 429),
        "usage_before_error": True,
        "times": RATE_LIMIT_TIMES,
        "answer": "nəhayət cavab",
        "usage": {"input_tokens": 800, "output_tokens": 30},
    },
    AUTH_ERROR: {"error": ("unauthorized", "Access token is invalid", 401)},
    BAD_REQUEST_ERROR: {"error": ("invalid_param", "sorğu qəbul edilmədi", 400)},
    CREDIT_ERROR: {"error": ("completion_request_error", CREDIT_EXHAUSTED_MESSAGE, 400)},
}


def _json_multi_turn_script() -> dict[str, Any]:
    """Yaddaşı OLAN hədəf: cavab `conversation_id` üzrə tarixçəyə görə qurulur."""
    history: dict[str, list[str]] = {}

    def reply(body: dict[str, Any]) -> dict[str, Any]:
        conv = str(body.get("conversation_id") or "")
        query = str(body.get("message", ""))
        turns = history.setdefault(conv, [])
        turns.append(query)
        known = next((t.split("ORD-")[1][:5] for t in turns if "ORD-" in t), None)
        if "çatdırıldı" in query:
            answer = (
                f"ORD-{known} 2026-08-20-də çatdırılıb."
                if known
                else "Hansı sifarişi nəzərdə tutursunuz?"
            )
        else:
            answer = "Anladım."
        spec: dict[str, Any] = {"answer": answer}
        if len(turns) == MULTI_TURN_TURN_WITH_TOOL:
            spec["tool_calls"] = [
                {"name": MULTI_TURN_TOOL, "arguments": {"order_id": MULTI_TURN_ORDER_ID},
                 "result": {"ok": True}}
            ]
        return spec

    return {"side_effect": reply, "usage": {"input_tokens": 100, "output_tokens": 20}}


class JsonHttpTarget(ConformanceTarget):
    """`json_http` + `mock_json_agent` (real HTTP, bloklayıcı JSON gövdə)."""

    label = "json_http"
    supports = frozenset(CAPABILITIES)
    max_rate_limit_retries = 2

    def __init__(self) -> None:
        self._server = MockJsonAgentServer(query_field="message")
        self._adapter: Any = None

    def start(self) -> "JsonHttpTarget":
        self._server.start()
        return self

    def stop(self) -> None:
        self._server.stop()

    def adapter(self) -> Any:
        if self._adapter is None:
            self._adapter = create_adapter(
                "json_http",
                url=self._server.url,
                api_key=self._server.api_key,
                query_field="message",
                backoff_base_s=0.01,  # test saatı
                max_rate_limit_retries=self.max_rate_limit_retries,
                # Çoxnövbəlilik AÇIQ şəkildə elan olunur — təxmin edilmir.
                conversation_id_path=CUSTOM_CONVERSATION_PATH,
                **CUSTOM_MAP,
            )
        return self._adapter

    def unreachable_adapter(self) -> Any:
        return create_adapter("json_http", url="http://127.0.0.1:9/invoke", api_key="x")

    def requests_sent(self) -> int:
        return len(self._server.request_log)

    def arrange(self, scenario: str) -> AgentRequest:
        if scenario == MULTI_TURN:
            self._server.scripted[NEEDLE[MULTI_TURN]] = _json_multi_turn_script()
            return AgentRequest(
                messages=_multi_turn_messages(),
                session_id="conformance-multi-turn",
                metadata={"case_id": "conformance-multi-turn"},
            )
        self._server.scripted[NEEDLE[scenario]] = dict(JSON_SCRIPTS[scenario])
        return _one(scenario)


# ====================================================== körpü 4: `callable`
GRAPH_SCRIPTS: dict[str, dict[str, Any]] = {
    OK: {
        "answer": "Açılmış məhsullarda 15% restocking haqqı tutulur.",
        "retrieved": [OK_CHUNK],
        "tool_calls": [OK_TOOL],
        "usage": {"input_tokens": 1820, "output_tokens": 190},
    },
    SLOW: {"answer": "gec cavab", "delay_ms": SLOW_MS,
           "usage": {"input_tokens": 10, "output_tokens": 5}},
    NO_USAGE: {"answer": "token hesabı olmayan cavab"},
    NO_RETRIEVAL: {"answer": "bilik bazasına toxunmayan cavab",
                   "usage": {"input_tokens": 10, "output_tokens": 5}},
    EMPTY: {"answer": ""},
    # Xəta `return` ilə deyil, `raise` ilə gəlir — real SDK-lardakı kimi.
    AUTH_ERROR: {"raises": ("unauthorized", "Access token is invalid")},
    BAD_REQUEST_ERROR: {"raises": ("invalid_request", "order_id is required")},
    CREDIT_ERROR: {"raises": ("upstream", CREDIT_EXHAUSTED_MESSAGE)},
    RATE_LIMIT_ALWAYS: {"raises": ("rate_limited", RATE_LIMIT_MESSAGE)},
}


def _graph_multi_turn_script() -> dict[str, Any]:
    def reply(query: str, turns: list[str]) -> dict[str, Any]:
        known = next((t.split("ORD-")[1][:5] for t in turns if "ORD-" in t), None)
        if "çatdırıldı" in query:
            answer = (
                f"ORD-{known} 2026-08-20-də çatdırılıb."
                if known
                else "Hansı sifarişi nəzərdə tutursunuz?"
            )
        else:
            answer = "Anladım."
        spec: dict[str, Any] = {"answer": answer}
        if len(turns) == MULTI_TURN_TURN_WITH_TOOL:
            spec["tool_calls"] = [
                {"name": MULTI_TURN_TOOL, "arguments": {"order_id": MULTI_TURN_ORDER_ID},
                 "result": {"ok": True}}
            ]
        return spec

    return {"side_effect": reply, "usage": {"input_tokens": 100, "output_tokens": 20}}


def _unhealthy() -> bool:
    raise ConnectionError("qraf işə düşməyib")


class CallableTarget(ConformanceTarget):
    """`callable` + `fake_graph` — şəbəkəsiz, amma REAL çağırış."""

    label = "callable"
    #: Boşluq `CALLABLE_GAP`-də ADI ilə kilidlənib: şəbəkə olmadığı üçün
    #: gözləməklə keçən 429 və "atılan cəhdin tokeni" ssenariləri YOXDUR.
    supports = frozenset(set(CAPABILITIES) - {RATE_LIMIT_THEN_OK, RATE_LIMIT_BURNS_TOKENS})
    #: Təkrar QƏSDƏN sıfırdır (bax `callable_agent.py` docstring-i).
    max_rate_limit_retries = 0

    def __init__(self) -> None:
        self._graph = FakeSupportGraph(
            scripted={NEEDLE[s]: dict(v) for s, v in GRAPH_SCRIPTS.items()}
        )
        self._adapter: Any = None

    def adapter(self) -> Any:
        if self._adapter is None:
            self._adapter = create_adapter("callable", fn=self._graph.answer, **GRAPH_MAP)
        return self._adapter

    def unreachable_adapter(self) -> Any:
        return create_adapter("callable", fn=self._graph.answer, health_fn=_unhealthy)

    def requests_sent(self) -> int:
        return self._graph.calls

    def arrange(self, scenario: str) -> AgentRequest:
        if scenario == MULTI_TURN:
            self._graph.scripted[NEEDLE[MULTI_TURN]] = _graph_multi_turn_script()
            return AgentRequest(
                messages=_multi_turn_messages(),
                session_id="conformance-multi-turn",
                metadata={"case_id": "conformance-multi-turn"},
            )
        return _one(scenario)


TARGETS: dict[str, type[ConformanceTarget]] = {
    "callable": CallableTarget,
    "dify_http": DifyHttpTarget,
    "json_http": JsonHttpTarget,
    "mock": MockTarget,
}


# ================================================================ DƏST QAÇIR
@pytest.mark.parametrize("check", CONTRACT, ids=[c.name for c in CONTRACT])
@pytest.mark.parametrize("target_name", sorted(TARGETS))
@pytest.mark.asyncio
async def test_adapter_contract(target_name: str, check) -> None:
    target_cls = TARGETS[target_name]
    missing = tuple(n for n in check.needs if n not in target_cls.supports)
    if missing:
        pytest.skip(f"{target_name} bu ssenarini hazırlaya bilmir: {', '.join(missing)}")
    with target_cls() as target:
        await check.run(target)


# ====================================================== DƏSTƏK MATRİSİ KİLİD
#: `mock` in-process olduğu üçün BU dördünü hazırlaya bilmir. Siyahı burada
#: KİLİDLƏNİR: bir adapter sabah səssizcə "dəstəkləmirəm" deyə bilməsin.
MOCK_GAP = (
    HALTS_RUN,
    MULTI_TURN,
    RATE_LIMIT_ALWAYS,
    RATE_LIMIT_BURNS_TOKENS,
    RATE_LIMIT_THEN_OK,
    UNREACHABLE,
)

#: `callable` şəbəkəsizdir: gözləməklə keçən 429 və "backoff zamanı yanan
#: token" ssenariləri onda MÖVCUD DEYİL (AP-031). Qalan hər şey — HALT,
#: çoxnövbəli zəncir, təsnifat — eynidir, çünki nüvə eynidir.
#:
#: DİQQƏT: bu boşluq `mock`-unkundan KEÇƏRLİ olaraq kiçikdir. `RATE_LIMIT_ALWAYS`
#: burada QAÇIR: təkrar sayı sıfır olsa da səbəb `rate_limit` adı ilə qalmalıdır
#: — "unknown" yığınına düşsəydi, in-process hədəfin daxili rate limit-i
#: hesabatda görünməzdi.
CALLABLE_GAP = (RATE_LIMIT_BURNS_TOKENS, RATE_LIMIT_THEN_OK)


def test_the_suite_is_not_thin():
    """DoD: ən azı 8 ayrı müqavilə şərti."""
    assert len(CONTRACT) >= 8
    assert len({c.name for c in CONTRACT}) == len(CONTRACT), "təkrarlanan yoxlama adı"
    assert all(c.why.strip() for c in CONTRACT), "hər yoxlama NİYƏ mövcud olduğunu deməlidir"


@pytest.mark.parametrize("target_cls", [DifyHttpTarget, JsonHttpTarget],
                         ids=["dify_http", "json_http"])
def test_the_real_adapters_run_every_check(target_cls):
    """ŞƏBƏKƏYƏ çıxan adapterlərdə BOŞLUQ OLMAMALIDIR."""
    assert target_cls.supports == frozenset(CAPABILITIES)
    assert all(not c.missing(target_cls) for c in CONTRACT)  # type: ignore[arg-type]


def test_the_mock_gap_is_named_not_silent():
    assert tuple(sorted(set(CAPABILITIES) - MockTarget.supports)) == MOCK_GAP
    skipped = [c.name for c in CONTRACT if any(n in MOCK_GAP for n in c.needs)]
    # Boşluq REAL və KİÇİKDİR: yoxlamaların böyük hissəsi mock-da da qaçır.
    assert 0 < len(skipped) < len(CONTRACT) // 2, skipped


def test_the_callable_gap_is_named_not_silent():
    """`callable` sabah səssizcə "bunu da dəstəkləmirəm" deyə bilməsin."""
    assert tuple(sorted(set(CAPABILITIES) - CallableTarget.supports)) == CALLABLE_GAP
    skipped = [c.name for c in CONTRACT if any(n in CALLABLE_GAP for n in c.needs)]
    assert len(skipped) == 2, skipped
    # Şəbəkəsiz adapterin boşluğu skriptləşdirilmiş mock-unkundan KİÇİK olmalıdır:
    # `callable` REAL çağırış edir, `mock` etmir.
    assert len(CALLABLE_GAP) < len(MOCK_GAP)


def test_every_adapter_is_wired_into_the_suite():
    """Qeydiyyatdakı hər adapterin uyğunluq körpüsü olmalıdır.

    Olmasaydı, yeni adapter yazan adam dəsti QOŞMADAN da yaşıl `pytest`
    görərdi — müqavilə isə yalnız qoşulanda qorunur.
    """
    from agentproof.adapters import adapter_names

    assert sorted(TARGETS) == adapter_names()


# =============================================== DƏST BOŞ YAŞIL DEYİL (mənfi)
class _SloppyAgent:
    """Müqaviləni QƏSDƏN pozan adapter — dəstin dişlədiyini sübut edir.

    Üç tipik pozuntu: ölçülməyən istifadəni sıfır kimi göstərmək, boş cavabı
    səssiz keçirmək, xətanı təsnif etmədən qaytarmaq.
    """

    name = "sloppy"
    version = "0"

    async def health(self) -> bool:
        return True

    async def invoke(self, req: AgentRequest) -> AgentResponse:
        query = req.query
        text = "" if NEEDLE[EMPTY] in query else "hər şey qaydasındadır"
        return AgentResponse(
            text=text,
            retrieved=[RetrievedChunk(chunk_id="x")] if NEEDLE[OK] in query else [],
            tool_calls=[ToolCall(name="lookup_order")],
            # ← `None` olmalı idi. Model etiketi ilə birlikdə bu, hesabatda
            # "$0.00 — büdcədən aşağı, KEÇDİ" kimi görünür: inandırıcı və yalan.
            usage=Usage(input_tokens=0, output_tokens=0, model="claude-sonnet-5"),
            latency_ms=0,  # ← ölçülmür
            error="unauthorized" if NEEDLE[AUTH_ERROR] in query else None,
            error_class=None,  # ← təsnif edilmir
        )


class SloppyTarget(MockTarget):
    label = "sloppy"

    def adapter(self) -> Any:
        if self._adapter is None:
            self._adapter = _SloppyAgent()
        return self._adapter

    def requests_sent(self) -> int:
        return 0


@pytest.mark.parametrize(
    "check_name",
    [
        "usage_missing_means_none_not_zero",
        "cost_grader_skips_when_usage_is_missing",
        "empty_answer_is_named_not_silent",
        "latency_is_filled_by_the_adapter",
        "auth_error_is_not_retried",
    ],
)
@pytest.mark.asyncio
async def test_contract_breaker_fails_the_suite(check_name: str) -> None:
    """Pozuntu YOXLAMANI SINDIRMALIDIR — əks halda dəst boş yaşıldır."""
    check = next(c for c in CONTRACT if c.name == check_name)
    with SloppyTarget() as target:
        with pytest.raises(AssertionError):
            await check.run(target)

"""AP-031 — in-process (callable) adapter.

Uyğunluq dəsti `callable` üçün 23 yoxlama qaçırır (2 boşluq `CALLABLE_GAP`-də
ADI ilə kilidlidir). Burada bu adapterin öz vədləri sınanır:

  * `fn` sync və ya async ola bilər, hər ikisi eyni cavabı verir;
  * `fn` istisna atsa qaçış SINMIR — xəta adlanır və TƏSNİF olunur;
  * backoff QƏSDƏN yoxdur və bu, susqun deyil: `rate_limit` bir cəhddən sonra
    tükənmiş sayılır, amma səbəb `rate_limit` ADI ilə qalır;
  * söhbət qəbul etməyən `fn` çoxnövbəli case-i ölçmür, ADI ilə imtina edir.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from agentproof.adapters import create_adapter
from agentproof.adapters._http_core import MULTI_TURN_UNSUPPORTED
from agentproof.adapters.callable_agent import accepts_conversation
from agentproof.failure import AUTH, BAD_REQUEST, CREDIT_EXHAUSTED, HALT, RATE_LIMIT
from agentproof.testing.fake_graph import (
    GRAPH_MAP,
    FakeSupportGraph,
    RateLimited,
    Unauthorized,
)
from agentproof.testing.mock_dify import CREDIT_EXHAUSTED_MESSAGE
from agentproof.types import AgentRequest, AgentResponse, RetrievedChunk, ToolCall, Usage

CHUNK = {
    "chunk_id": "returns-and-refunds#restocking",
    "document": "returns-and-refunds.md",
    "content": "Opened items are subject to a 15% restocking fee.",
    "score": 0.93,
}
TOOL = {"name": "lookup_order", "arguments": {"order_id": "ORD-10001"}, "result": {"ok": True}}


def _request(query: str) -> AgentRequest:
    return AgentRequest(messages=[{"role": "user", "content": query}], session_id="unit")


def _multi(*queries: str) -> AgentRequest:
    return AgentRequest(
        messages=[{"role": "user", "content": q} for q in queries], session_id="unit-mt"
    )


def _graph(**scripts: dict[str, Any]) -> FakeSupportGraph:
    return FakeSupportGraph(scripted=dict(scripts))


# ================================================= imza oxunması (təxmin yox)
def test_conversation_support_is_read_from_the_signature() -> None:
    assert accepts_conversation(lambda q: q) is False
    assert accepts_conversation(lambda q, conversation_id="": q) is True
    assert accepts_conversation(lambda q, cid: q) is True
    assert accepts_conversation(lambda q, **kw: q) is True
    # İmzası oxunmayan çağırılan -> "dəstəkləmir" (təhlükəsiz tərəf).
    assert accepts_conversation(len) is False


def test_multi_turn_can_be_declared_by_hand() -> None:
    """İmza oxunmayan sarğılar üçün `multi_turn=` açıq açardır."""
    adapter = create_adapter("callable", fn=lambda q: q, multi_turn=True)
    assert adapter.multi_turn is True


def test_fn_is_required() -> None:
    with pytest.raises(ValueError, match="fn"):
        create_adapter("callable")


# ================================================================ çağırış
@pytest.mark.asyncio
async def test_sync_and_async_callables_behave_identically() -> None:
    script = {
        "answer": "15% restocking fee.",
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "tool_calls": [TOOL],
        "retrieved": [CHUNK],
    }
    sync_graph, async_graph = _graph(q1=script), _graph(q1=script)
    sync = create_adapter("callable", fn=sync_graph.answer, **GRAPH_MAP)
    asynchronous = create_adapter("callable", fn=async_graph.aanswer, **GRAPH_MAP)

    a = await sync.invoke(_request("q1 sualı"))
    b = await asynchronous.invoke(_request("q1 sualı"))

    for response in (a, b):
        assert response.error is None
        assert response.text == "15% restocking fee."
        assert response.usage is not None and response.usage.input_tokens == 100
        assert [c.name for c in response.tool_calls] == ["lookup_order"]
        assert [c.chunk_id for c in response.retrieved] == [CHUNK["chunk_id"]]
        assert response.raw["transport"] == "in_process"


@pytest.mark.asyncio
async def test_a_plain_string_return_is_accepted() -> None:
    adapter = create_adapter("callable", fn=lambda q: f"cavab: {q}")
    response = await adapter.invoke(_request("salam"))
    assert response.error is None and response.text == "cavab: salam"


@pytest.mark.asyncio
async def test_an_agent_response_return_is_passed_through() -> None:
    """Hədəf müqaviləni ÖZÜ doldura bilir — sahələrinə toxunmuruq."""

    def fn(query: str) -> AgentResponse:
        return AgentResponse(
            text="hazır cavab",
            tool_calls=[ToolCall(name="lookup_order")],
            retrieved=[RetrievedChunk(chunk_id="c1")],
            usage=Usage(input_tokens=7, output_tokens=3),
        )

    response = await create_adapter("callable", fn=fn).invoke(_request("x"))
    assert response.text == "hazır cavab"
    assert response.usage is not None and response.usage.input_tokens == 7
    # Gecikməni hədəf ölçməyibsə ADAPTER doldurur (müqavilə şərti).
    assert response.latency_ms >= 0
    assert response.raw["transport"] == "in_process"


@pytest.mark.asyncio
async def test_map_response_runs_before_the_field_map() -> None:
    """Müştəri öz obyektini bir sətirlə lüğətə çevirir."""

    class Result:
        def __init__(self) -> None:
            self.content = "obyektdən gələn cavab"

    adapter = create_adapter(
        "callable",
        fn=lambda q: Result(),
        map_response=lambda r: {"reply": r.content},
        text_path="reply",
    )
    assert (await adapter.invoke(_request("x"))).text == "obyektdən gələn cavab"


@pytest.mark.asyncio
async def test_empty_answer_is_named_even_when_fn_builds_the_response() -> None:
    adapter = create_adapter("callable", fn=lambda q: AgentResponse(text="   "))
    response = await adapter.invoke(_request("x"))
    assert response.error == "empty_answer"
    assert response.error_class == "unknown"


@pytest.mark.asyncio
async def test_latency_is_measured_by_the_adapter() -> None:
    def slow(query: str) -> str:
        time.sleep(0.12)
        return "gec cavab"

    response = await create_adapter("callable", fn=slow).invoke(_request("x"))
    assert response.latency_ms >= 60, response.latency_ms


@pytest.mark.asyncio
async def test_a_blocking_callable_does_not_freeze_other_lanes() -> None:
    """Sinxron `fn` AYRI THREAD-də qaçır.

    Bloklasaydı, `--max-connections` ilə qaçan lane-lər növbəyə düzülərdi və
    ölçdüyümüz gecikmə hədəfin deyil, öz növbəmizin gecikməsi olardı.
    """
    adapter = create_adapter("callable", fn=lambda q: (time.sleep(0.15), "ok")[1])
    started = time.perf_counter()
    await asyncio.gather(*(adapter.invoke(_request(f"q{i}")) for i in range(4)))
    elapsed = time.perf_counter() - started
    assert elapsed < 0.45, f"4 paralel çağırış {elapsed:.2f}s çəkdi — ardıcıl qaçıb"


# ============================================================ xəta yolları
@pytest.mark.asyncio
async def test_an_exception_is_named_and_classified_not_raised() -> None:
    def boom(query: str) -> str:
        raise Unauthorized("Access token is invalid")

    response = await create_adapter("callable", fn=boom).invoke(_request("x"))
    assert response.error == "callable_exception:Unauthorized"
    assert response.error_class == AUTH
    assert response.raw["exception_type"] == "Unauthorized"
    assert response.raw["target_error"]["status"] == 401


@pytest.mark.asyncio
async def test_an_unclassifiable_exception_stays_unknown_not_guessed() -> None:
    def boom(query: str) -> str:
        raise ValueError("qraf düyünü çökdü")

    response = await create_adapter("callable", fn=boom).invoke(_request("x"))
    assert response.error == "callable_exception:ValueError"
    assert response.error_class == "unknown", "təsnif olunmayan xəta təxmin edilib"


@pytest.mark.asyncio
async def test_credit_exhaustion_inside_the_graph_halts_the_whole_run() -> None:
    """In-process agent da model API-sinə çıxır: kredit bitəndə qaçış dayanır."""
    graph = _graph(q2={"raises": ("upstream", CREDIT_EXHAUSTED_MESSAGE)},
                   q3={"answer": "bu cavab heç vaxt gəlməməlidir"})
    adapter = create_adapter("callable", fn=graph.answer, **GRAPH_MAP)

    first = await adapter.invoke(_request("q2 sualı"))
    assert first.error_class == CREDIT_EXHAUSTED
    assert HALT.tripped

    calls = graph.calls
    later = await adapter.invoke(_request("q3 sualı"))
    assert graph.calls == calls, "qaçış dayanıb, amma qrafa çağırış getdi"
    assert later.error is not None and later.error.startswith("halted:")
    assert later.attempts == 0


@pytest.mark.asyncio
async def test_rate_limit_is_not_retried_but_stays_named() -> None:
    """AP-031 qərarı: şəbəkə yoxdur -> backoff yoxdur. SƏBƏB isə itmir.

    `unknown` yığınına düşsəydi, in-process hədəfin daxili rate limit-i
    hesabatda "səbəbi bilinməyən uğursuzluq" kimi görünərdi.
    """
    calls = {"n": 0}

    def limited(query: str) -> str:
        calls["n"] += 1
        raise RateLimited("Number of request tokens has exceeded your rate limit.")

    response = await create_adapter("callable", fn=limited).invoke(_request("x"))
    assert calls["n"] == 1, f"{calls['n']} çağırış — təkrar EDİLMƏMƏLİDİR"
    assert response.error_class == RATE_LIMIT
    assert response.raw["retry_exhausted"] is True
    assert "retry_waits_s" not in response.raw, "gözləmə baş verdi — backoff işləyib"
    assert response.attempts == 1


# ============================================================= çoxnövbəli
@pytest.mark.asyncio
async def test_multi_turn_keeps_context_through_the_graph_memory() -> None:
    def reply(query: str, turns: list[str]) -> dict[str, Any]:
        known = next((t.split("ORD-")[1][:5] for t in turns if "ORD-" in t), None)
        return {"answer": f"ORD-{known} çatdırılıb." if known and "nə vaxt" in query
                else "Anladım."}

    graph = _graph(q4={"side_effect": reply, "usage": {"input_tokens": 5, "output_tokens": 2}})
    adapter = create_adapter("callable", fn=graph.answer, **GRAPH_MAP)
    response = await adapter.invoke(
        _multi("q4 sifarişim ORD-10001.", "q4 təşəkkür.", "q4 nə vaxt çatdırıldı?")
    )

    assert response.error is None
    assert response.n_turns == 3
    assert response.raw["conversation_chained"] is True
    assert "ORD-10001" in response.text
    # Xərc BÜTÖV söhbətə görədir.
    assert response.usage is not None and response.usage.input_tokens == 15


@pytest.mark.asyncio
async def test_multi_turn_is_refused_when_fn_takes_no_conversation() -> None:
    calls = {"n": 0}

    def single(query: str) -> str:
        calls["n"] += 1
        return "cavab"

    response = await create_adapter("callable", fn=single).invoke(_multi("bir", "iki"))
    assert response.error == MULTI_TURN_UNSUPPORTED
    assert response.error_class == BAD_REQUEST
    assert calls["n"] == 0, "ölçülməyəcək case üçün hədəf çağırıldı"
    assert response.raw["multi_turn_supported"] is False


@pytest.mark.asyncio
async def test_a_broken_turn_stops_the_rest_of_the_conversation() -> None:
    calls: list[str] = []

    def flaky(query: str, conversation_id: str = "") -> str:
        calls.append(query)
        if "ikinci" in query:
            raise RateLimited("slow down")
        return "ok"

    response = await create_adapter("callable", fn=flaky).invoke(
        _multi("birinci", "ikinci", "üçüncü")
    )
    assert [c for c in calls if "üçüncü" in c] == [], "zəncir qırıldı, növbə yenə getdi"
    assert response.error_class == RATE_LIMIT
    assert response.n_turns == 2


# ================================================================== health
@pytest.mark.asyncio
async def test_health_is_false_when_the_graph_refuses_to_start() -> None:
    def unhealthy() -> bool:
        raise ConnectionError("qraf işə düşməyib")

    adapter = create_adapter("callable", fn=lambda q: "x", health_fn=unhealthy)
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_health_without_a_probe_only_proves_the_callable_exists() -> None:
    assert await create_adapter("callable", fn=lambda q: "x").health() is True

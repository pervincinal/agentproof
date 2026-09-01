"""AP-029 — nüvə HƏDƏFSİZ işləyir: backoff, zəncir və birləşmə Dify-siz.

`_http_core.py`-nin bütün girişi bir funksiyadır: `send_once()`. Aşağıdakı
testlərdə o funksiya nə HTTP açır, nə SSE oxuyur — sadəcə hazır
`AgentResponse` qaytarır. Yəni "bu məntiq Dify-yə xas deyil" iddiası burada
İCRA OLUNUR: ikinci adapter (in-process SDK, gRPC, nə olursa) eyni qaydaları
sıfır sətir yazmadan alır.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentproof.adapters._http_core import (
    MISSING_CONVERSATION_ID,
    RetryPolicy,
    merge_turns,
    run_conversation,
    send_with_retry,
    sum_usage,
    user_turns,
)
from agentproof.failure import HALT
from agentproof.types import AgentResponse, RetrievedChunk, ToolCall, Usage

FAST = RetryPolicy(max_retries=3, base_s=0.01, cap_s=1.0)


def _resp(**kw: Any) -> AgentResponse:
    kw.setdefault("text", "ok")
    return AgentResponse(**kw)


def _rate_limited(usage: Usage | None = None, retry_after: Any = None) -> AgentResponse:
    return AgentResponse(
        text="",
        usage=usage,
        error="too_many_requests",
        error_class="rate_limit",
        raw={"retry_after_s": retry_after},
    )


def _scripted(responses: list[AgentResponse]):
    """`send_once` — hədəf YOXDUR, sadəcə növbəti hazır cavab."""
    calls = {"n": 0}

    async def send_once() -> AgentResponse:
        index = calls["n"]
        calls["n"] += 1
        return responses[min(index, len(responses) - 1)]

    return send_once, calls


# ============================================================ 1. təkrar maşını
@pytest.mark.asyncio
async def test_rate_limit_is_retried_until_the_target_recovers():
    send, calls = _scripted([_rate_limited(), _rate_limited(), _resp()])
    response = await send_with_retry(send, policy=FAST)

    assert response.error is None
    assert calls["n"] == 3 and response.attempts == 3
    waits = response.raw["retry_waits_s"]
    assert len(waits) == 2 and waits[1] > waits[0], waits


@pytest.mark.asyncio
async def test_non_retryable_classes_return_immediately():
    """Nüvə sinfə baxır, koda yox — hansı wire formatından gəldiyi ƏHƏMİYYƏTSİZDİR."""
    for reason in ("auth", "bad_request", "unknown"):
        send, calls = _scripted(
            [AgentResponse(text="", error="nə olursa olsun", error_class=reason)]
        )
        response = await send_with_retry(send, policy=FAST)
        assert calls["n"] == 1, reason
        assert response.attempts == 1
        assert "retry_waits_s" not in response.raw


@pytest.mark.asyncio
async def test_exhausted_retries_are_named_not_swallowed():
    send, calls = _scripted([_rate_limited()])
    response = await send_with_retry(send, policy=RetryPolicy(max_retries=2, base_s=0.01))
    assert calls["n"] == 3
    assert response.raw["retry_exhausted"] is True
    assert response.error_class == "rate_limit"


@pytest.mark.asyncio
async def test_burned_tokens_of_discarded_attempts_are_kept():
    """AP-026: atılan cəhdin tokeni uğurlu cavabın `usage`-ına QATILMIR."""
    burned = Usage(input_tokens=800, output_tokens=30)
    send, _ = _scripted([_rate_limited(burned), _rate_limited(burned), _resp(usage=Usage(10, 5))])
    response = await send_with_retry(send, policy=FAST, model="m")

    assert response.usage == Usage(10, 5)
    assert response.retry_usage == Usage(input_tokens=1600, output_tokens=60, model="m")
    assert response.raw["measured_retries"] == 2


@pytest.mark.asyncio
async def test_unmeasured_retries_are_not_reported_as_zero():
    """Tokeni bilinməyən cəhd SIFIR deyil, NAMƏLUMDUR — `retry_usage` boş qalır."""
    send, _ = _scripted([_rate_limited(), _rate_limited(), _resp()])
    response = await send_with_retry(send, policy=FAST)
    assert response.retry_usage is None
    assert response.raw["measured_retries"] == 0


@pytest.mark.asyncio
async def test_retry_after_beats_the_exponential_guess():
    send, _ = _scripted([_rate_limited(retry_after="0.02"), _resp()])
    response = await send_with_retry(send, policy=RetryPolicy(max_retries=3, base_s=10.0))
    assert response.raw["retry_waits_s"] == [0.02]


@pytest.mark.asyncio
async def test_halting_class_trips_the_run_and_later_calls_send_nothing():
    HALT.reset()
    try:
        send, calls = _scripted(
            [AgentResponse(text="", error="completion_request_error",
                           error_class="credit_exhausted")]
        )
        first = await send_with_retry(send, policy=FAST, case_id="case-01")
        assert calls["n"] == 1 and HALT.tripped and HALT.case_id == "case-01"

        later = await send_with_retry(send, policy=FAST, context={"query": "sonrakı"})
        assert calls["n"] == 1, "qaçış dayanıb — sorğu getməməli idi"
        assert later.error == "halted:credit_exhausted"
        assert later.attempts == 0 and later.raw["request_sent"] is False
        assert later.raw["query"] == "sonrakı"
        assert first.attempts == 1
    finally:
        HALT.reset()


# ============================================================== 2. söhbət zənciri
@pytest.mark.asyncio
async def test_conversation_id_is_chained_from_the_first_response():
    sent: list[str] = []

    async def send_turn(query: str, conversation_id: str, index: int) -> AgentResponse:
        sent.append(conversation_id)
        return _resp(text=f"t{index}", raw={"conversation_id": "conv-1"})

    turns = await run_conversation(send_turn, ["a", "b", "c"])
    assert sent == ["", "conv-1", "conv-1"]
    assert [t.text for t in turns] == ["t0", "t1", "t2"]


@pytest.mark.asyncio
async def test_chain_stops_at_the_first_failing_turn():
    """Davam etsəydik, YENİ söhbət açılardı — çoxnövbəli case gizlicə tək-növbəli."""
    async def send_turn(query: str, conversation_id: str, index: int) -> AgentResponse:
        if index == 1:
            return AgentResponse(text="", error="auth_x", error_class="auth")
        return _resp(raw={"conversation_id": "conv-1"})

    turns = await run_conversation(send_turn, ["a", "b", "c"])
    assert len(turns) == 2, "3-cü növbə göndərilməməli idi"


@pytest.mark.asyncio
async def test_missing_conversation_id_is_named():
    async def send_turn(query: str, conversation_id: str, index: int) -> AgentResponse:
        return _resp(raw={})

    turns = await run_conversation(send_turn, ["a", "b"])
    assert len(turns) == 1
    assert turns[0].error == MISSING_CONVERSATION_ID


@pytest.mark.asyncio
async def test_single_turn_without_conversation_id_is_not_an_error():
    async def send_turn(query: str, conversation_id: str, index: int) -> AgentResponse:
        return _resp(raw={})

    turns = await run_conversation(send_turn, ["a"])
    assert turns[0].error is None


def test_scripted_assistant_turns_are_dropped_and_counted():
    queries, dropped = user_turns(
        [
            {"role": "user", "content": "birinci"},
            {"role": "assistant", "content": "skript"},
            {"role": "user", "content": "  "},
            {"role": "user", "content": "ikinci"},
        ],
        fallback="ehtiyat",
    )
    assert queries == ["birinci", "ikinci"]
    assert dropped == 1


def test_empty_message_list_falls_back_to_the_query():
    assert user_turns([], fallback="ehtiyat") == (["ehtiyat"], 0)


# ================================================================ 3. birləşmə
def _turn(text: str, tool: str | None = None, chunk: str | None = None,
          usage: Usage | None = None, latency: int = 5) -> AgentResponse:
    return AgentResponse(
        text=text,
        tool_calls=[ToolCall(name=tool)] if tool else [],
        retrieved=[RetrievedChunk(chunk_id=chunk)] if chunk else [],
        usage=usage,
        latency_ms=latency,
        raw={"conversation_id": "conv-1"},
    )


def test_merge_unions_tool_calls_and_sums_cost():
    turns = [
        _turn("bir", tool="lookup_order", chunk="c1", usage=Usage(100, 20)),
        _turn("iki", tool="initiate_return", chunk="c1", usage=Usage(150, 30)),
        _turn("üç", chunk="c2", usage=Usage(50, 10)),
    ]
    merged = merge_turns(turns, dropped=0, model="m", transport="x")

    assert merged.text == "üç", "yekun mətn SONUNCU növbənindir"
    assert [c.name for c in merged.tool_calls] == ["lookup_order", "initiate_return"]
    assert [c.chunk_id for c in merged.retrieved] == ["c1", "c2"], "təkrar chunk birləşir"
    assert merged.usage == Usage(input_tokens=300, output_tokens=60, model="m")
    assert merged.latency_ms == 15
    assert merged.raw["conversation_chained"] is True
    assert merged.raw["transport"] == "x"
    assert merged.turns == turns


def test_merge_keeps_the_first_error_and_its_class():
    turns = [
        _turn("bir"),
        AgentResponse(text="", error="birinci", error_class="auth"),
        AgentResponse(text="", error="ikinci", error_class="unknown"),
    ]
    merged = merge_turns(turns, dropped=0)
    assert merged.error == "birinci" and merged.error_class == "auth"
    assert merged.raw["turn_errors"] == [None, "birinci", "ikinci"]


def test_single_turn_is_returned_unwrapped():
    turn = _turn("tək")
    assert merge_turns([turn], dropped=0) is turn


def test_single_turn_with_dropped_history_is_wrapped_so_the_count_survives():
    turn = _turn("tək")
    merged = merge_turns([turn], dropped=2)
    assert merged is not turn
    assert merged.raw["dropped_scripted_assistant_turns"] == 2


def test_merge_reports_no_usage_when_no_turn_measured_it():
    merged = merge_turns([_turn("a"), _turn("b")], dropped=0, model="m")
    assert merged.usage is None, "ölçülməyən istifadə sıfır kimi göstərilməməlidir"


def test_sum_usage_of_nothing_is_none_not_zero():
    assert sum_usage([]) is None
    assert sum_usage([None, None]) is None
    assert sum_usage([Usage(1, 2), None]) == Usage(input_tokens=1, output_tokens=2)

"""`dify_http` adapteri mock Dify wire formatına qarşı.

Real Dify qalxanda dəyişən yalnız `base_url` + açar olmalıdır — bu testlər
formatın özünü kilidləyir.
"""

from __future__ import annotations

import pytest

from agentproof.adapters import create_adapter
from agentproof.testing.mock_dify import MockDifyServer, aurora_fixture
from agentproof.types import AgentRequest


@pytest.fixture
def server():
    srv = MockDifyServer(scripted=aurora_fixture()).start()
    try:
        yield srv
    finally:
        srv.stop()


def _adapter(server: MockDifyServer, **kw):
    # `backoff_base_s` kiçikdir: bu fayl backoff-un ÖZÜNÜ deyil, wire formatını
    # kilidləyir. Backoff davranışı `test_rate_limit_backoff.py`-dədir.
    kw.setdefault("backoff_base_s", 0.01)
    return create_adapter("dify_http", base_url=server.base_url, api_key=server.api_key, **kw)


def _req(query: str) -> AgentRequest:
    return AgentRequest(messages=[{"role": "user", "content": query}], session_id="t")


@pytest.mark.asyncio
async def test_health_true_with_valid_key(server):
    assert await _adapter(server).health() is True


@pytest.mark.asyncio
async def test_health_false_without_key(server):
    """Açar YOXDURSA şəbəkəyə çıxmadan False — CI-da açarsız qaçış aydın fail verir."""
    assert await create_adapter("dify_http", base_url=server.base_url, api_key="").health() is False


@pytest.mark.asyncio
async def test_health_false_with_wrong_key(server):
    adapter = create_adapter("dify_http", base_url=server.base_url, api_key="app-yanlis")
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_invoke_parses_answer_usage_and_retrieval(server):
    response = await _adapter(server).invoke(_req("Restocking haqqı nə qədərdir?"))
    assert "15%" in response.text
    assert response.usage is not None
    assert response.usage.input_tokens == 1820
    assert response.usage.output_tokens == 190
    assert [c.chunk_id for c in response.retrieved] == ["returns-and-refunds#restocking"]
    assert response.retrieved[0].document == "returns-and-refunds.md"
    assert response.latency_ms >= 0
    assert response.error is None


@pytest.mark.asyncio
async def test_invoke_extracts_tool_calls_from_agent_thoughts(server):
    response = await _adapter(server).invoke(_req("Hədiyyə kartını qaytara bilərəm?"))
    assert [t.name for t in response.tool_calls] == ["escalate_to_human"]
    # Dify `tool_input`-u {"tool_adı": {...}} kimi verir — adapter açır
    assert response.tool_calls[0].arguments["reason"].startswith("gift card")
    assert response.tool_calls[0].result == {"ticket": "T-1001"}


@pytest.mark.asyncio
async def test_each_case_starts_a_fresh_conversation(server):
    """SETUP.md §7.2: `conversation_id` boş qalır ki, case-lər bir-birini çirkləndirməsin."""
    adapter = _adapter(server)
    await adapter.invoke(_req("Restocking haqqı?"))
    await adapter.invoke(_req("Restocking haqqı?"))
    assert all(body["conversation_id"] == "" for body in server.request_log)
    # `blocking` DƏSTƏKLƏNMİR — adapter həmişə streaming göndərir (PLAN.md "DÜZƏLİŞ")
    assert all(body["response_mode"] == "streaming" for body in server.request_log)
    assert all(body["user"] for body in server.request_log)


@pytest.mark.asyncio
async def test_infra_error_is_flagged_not_treated_as_content(server):
    """429 / provider xətası hallucination kimi sayılmamalıdır (SETUP.md §7.2)."""
    server.scripted["rate limited"] = {
        "error": ("rate_limit_error", "upstream rate limit", 429)
    }
    response = await _adapter(server).invoke(_req("rate limited sual"))
    assert response.error == "rate_limit_error"
    assert response.text == ""
    assert response.usage is None


@pytest.mark.asyncio
async def test_unauthorized_is_surfaced_as_infra_error(server):
    adapter = create_adapter("dify_http", base_url=server.base_url, api_key="app-yanlis")
    response = await adapter.invoke(_req("istənilən sual"))
    assert response.error == "unauthorized"


@pytest.mark.asyncio
async def test_adapter_retries_only_the_rate_limit_class(server):
    """Müqavilə (STACK.md §8.2, AP-024 ilə dəqiqləşdirilib).

    Adapter ümumi retry etmir — Inspect-in işini əvəz etmir. YEGANƏ istisna
    `rate_limit` sinfidir, çünki onu Inspect görmür: 429 hədəfin İÇİNDƏN
    (`completion_request_error` zərfində) gəlir və Inspect üçün bu, uğurlu
    200 cavabdır.
    """
    server.scripted["flaky"] = {"error": ("too_many_requests", "slow down", 429)}
    before = len(server.request_log)
    await _adapter(server, max_rate_limit_retries=2).invoke(_req("flaky sual"))
    assert len(server.request_log) - before == 3  # 1 ilk cəhd + 2 təkrar

    server.scripted["xarab sorğu"] = {"error": ("invalid_param", "user is required", 400)}
    before = len(server.request_log)
    await _adapter(server).invoke(_req("xarab sorğu"))
    assert len(server.request_log) - before == 1, "rate limit olmayan xəta təkrarlanmamalıdır"


# ------------------------------------------------------------------ SSE yolu
# `blocking` DƏSTƏKLƏNMİR: Agent Chat app-i icra yolunun dibində rədd edir
# (`app_generator.py:94`), canlı sistemdə 400 ilə təsdiqləndi. Aşağıdakı
# testlər adapterin SSE yolunu və onun XƏTA davranışını kilidləyir.


@pytest.mark.asyncio
async def test_blocking_mode_is_rejected_by_the_target(server):
    """Stub reallığı təkrarlayır: `blocking` -> 400. Adapter bunu göndərməməlidir."""
    import httpx

    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{server.base_url}/chat-messages",
            headers={"Authorization": f"Bearer {server.api_key}"},
            json={"query": "x", "user": "u", "response_mode": "blocking"},
        )
    assert r.status_code == 400
    assert "does not support blocking mode" in r.json()["message"]


@pytest.mark.asyncio
async def test_answer_is_assembled_from_multiple_agent_message_chunks(server):
    """Cavab bir parça deyil — axındakı bütün `agent_message`-lər birləşdirilir."""
    response = await _adapter(server).invoke(_req("Restocking haqqı nə qədərdir?"))
    counts = response.raw["sse_event_counts"]
    assert counts["agent_message"] > 1, "test parçalanmanı yoxlamırsa mənasızdır"
    assert response.text.startswith("Aurora Goods")
    assert response.text.endswith("tutulur.")
    assert response.raw["saw_message_end"] is True


@pytest.mark.asyncio
async def test_parallel_tools_in_one_thought_are_split_into_ordered_calls(server):
    """Canlı formatda `tool` sahəsi `;` ilə birləşir: 'check_return_eligibility;dataset_<uuid>'."""
    server.scripted["ord-10015"] = {
        "answer": "Qaytarma pəncərəsi bağlanıb.",
        "parallel_tools": True,
        "tool_calls": [
            {
                "name": "check_return_eligibility",
                "arguments": {"order_id": "ORD-10015", "sku": "AG-PRT-660"},
                "result": {"days_since_delivery": 20},
            },
            {
                "name": "dataset_e1471e22_18f8_4b30_aeb1_012c048e38a5",
                "arguments": {"query": "standard return window days"},
                "result": {"hits": 4},
            },
        ],
    }
    response = await _adapter(server).invoke(_req("ORD-10015 qaytara bilərəm?"))
    assert [t.name for t in response.tool_calls] == [
        "check_return_eligibility",
        "dataset_e1471e22_18f8_4b30_aeb1_012c048e38a5",
    ]
    assert response.tool_calls[0].arguments == {"order_id": "ORD-10015", "sku": "AG-PRT-660"}
    assert response.tool_calls[0].result == {"days_since_delivery": 20}
    assert response.tool_calls[1].arguments == {"query": "standard return window days"}


@pytest.mark.asyncio
async def test_repeated_thought_ids_are_not_counted_twice(server):
    """`agent_thought` eyni `id` ilə iki dəfə gəlir (əvvəl tool, sonra observation)."""
    response = await _adapter(server).invoke(_req("ORD-1042 sifarişim?"))
    assert response.raw["sse_event_counts"]["agent_thought"] == 2, "stub təkrarı göndərməlidir"
    assert [t.name for t in response.tool_calls] == ["lookup_order"]  # bir dəfə


@pytest.mark.asyncio
async def test_tool_call_order_is_preserved(server):
    server.scripted["çoxaddım"] = {
        "answer": "hazırdır",
        "tool_calls": [
            {"name": "lookup_order", "arguments": {"order_id": "ORD-10015"}, "result": {}},
            {"name": "check_return_eligibility", "arguments": {}, "result": {}},
            {"name": "escalate_to_human", "arguments": {}, "result": {}},
        ],
    }
    response = await _adapter(server).invoke(_req("çoxaddım ssenari"))
    assert [t.name for t in response.tool_calls] == [
        "lookup_order",
        "check_return_eligibility",
        "escalate_to_human",
    ]


@pytest.mark.asyncio
async def test_usage_and_retrieval_come_from_message_end(server):
    response = await _adapter(server).invoke(_req("ORD-1042 sifarişim?"))
    assert response.usage is not None
    assert response.usage.input_tokens == 2400
    assert response.usage.output_tokens == 310
    assert response.raw["dify_usage"]["total_tokens"] == 2710
    # Dify öz xərcini STRING kimi verir — xam halda saxlanılır
    assert float(response.raw["dify_usage"]["total_price"]) > 0
    assert [c.chunk_id for c in response.retrieved] == ["returns-and-refunds#window"]
    assert response.retrieved[0].score == pytest.approx(0.91)  # string -> float


@pytest.mark.asyncio
async def test_usage_has_no_model_name_unless_configured(server):
    """Canlı Dify `usage`-da model adı VERMİR — etiket kənardan gəlir (PLAN.md risk #2)."""
    plain = await _adapter(server).invoke(_req("ORD-1042 sifarişim?"))
    assert plain.usage.model == ""
    labelled = await _adapter(server, model="claude-sonnet-5").invoke(_req("ORD-1042 sifarişim?"))
    assert labelled.usage.model == "claude-sonnet-5"


@pytest.mark.asyncio
async def test_ping_events_are_ignored(server):
    server.scripted["ping testi"] = {
        "answer": "cavab",
        "ping": True,
        "tool_calls": [{"name": "lookup_order", "arguments": {}, "result": {}}],
    }
    response = await _adapter(server).invoke(_req("ping testi"))
    assert response.error is None
    assert response.text == "cavab"
    assert response.raw["sse_event_counts"]["ping"] == 1


@pytest.mark.asyncio
async def test_truncated_stream_is_reported_not_silently_empty(server):
    """Yarımçıq kəsilən axın: qismən mətn qalır, AMMA xəta adı ilə görünür."""
    server.scripted["kəsilən"] = {"answer": "yarım cav", "truncate": True}
    response = await _adapter(server).invoke(_req("kəsilən axın"))
    assert response.error == "stream_incomplete"
    assert response.raw["saw_message_end"] is False


@pytest.mark.asyncio
async def test_missing_message_end_is_stream_incomplete(server):
    """Axın düzgün bağlanır, amma `message_end` yoxdur -> usage/retrieval itir."""
    server.scripted["yarımçıq"] = {"answer": "mətn var", "no_message_end": True}
    response = await _adapter(server).invoke(_req("yarımçıq axın"))
    assert response.error == "stream_incomplete"
    assert response.text == "mətn var"
    assert response.usage is None


@pytest.mark.asyncio
async def test_error_event_mid_stream_is_surfaced(server):
    server.scripted["axın xətası"] = {
        "answer": "başladı",
        "error_event": ("provider_quota_exceeded", "quota bitdi", 400),
    }
    response = await _adapter(server).invoke(_req("axın xətası"))
    assert response.error == "provider_quota_exceeded"
    assert response.raw["dify_error"]["message"] == "quota bitdi"


@pytest.mark.asyncio
async def test_unknown_error_event_is_prefixed_not_swallowed(server):
    server.scripted["naməlum xəta"] = {
        "answer": "",
        "error_event": ("some_new_dify_code", "gözlənilməyən", 500),
    }
    response = await _adapter(server).invoke(_req("naməlum xəta"))
    assert response.error == "unexpected:some_new_dify_code"


@pytest.mark.asyncio
async def test_empty_answer_is_named_not_silent(server):
    """`message_end` gəldi, mətn yoxdur — bu SƏSSİZ keçməməlidir."""
    server.scripted["boş cavab"] = {"answer": "", "usage": {"prompt_tokens": 10, "completion_tokens": 0}}
    response = await _adapter(server).invoke(_req("boş cavab"))
    assert response.error == "empty_answer"
    assert response.text == ""
    assert response.usage is not None  # usage yenə də toplanır


@pytest.mark.asyncio
async def test_malformed_data_line_is_counted_not_crashed(server):
    server.scripted["zibil sətir"] = {"answer": "yaxşı mətn", "malformed": True}
    response = await _adapter(server).invoke(_req("zibil sətir"))
    assert response.raw["sse_malformed_lines"] == 1
    assert response.text == "yaxşı mətn"
    assert response.error is None  # message_end gəldi -> cavab tamdır


@pytest.mark.asyncio
async def test_timeout_is_reported_as_stream_timeout(server):
    server.scripted["yavaş"] = {"answer": "gec", "delay_ms": 600}
    adapter = _adapter(server, timeout_s=0.2)
    response = await adapter.invoke(_req("yavaş cavab"))
    assert response.error == "stream_timeout"
    assert response.raw["saw_message_end"] is False

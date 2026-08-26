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
    assert all(body["response_mode"] == "blocking" for body in server.request_log)
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
async def test_adapter_does_not_retry_itself(server):
    """Müqavilə (STACK.md §8.2): retry Inspect-in işidir, adapterin yox."""
    server.scripted["flaky"] = {"error": ("too_many_requests", "slow down", 429)}
    before = len(server.request_log)
    await _adapter(server).invoke(_req("flaky sual"))
    assert len(server.request_log) - before == 1

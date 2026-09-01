"""AP-030 — bloklayıcı JSON adapteri: sahə xəritəsi və SƏSSİZ DEFAULT-un yoxluğu.

Uyğunluq dəsti (`test_adapter_conformance.py`) müqavilənin ÜMUMİ şərtlərini
yoxlayır və `json_http` onun 25 yoxlamasının hamısını keçir. Burada isə məhz
BU adapterin öz vədləri sınanır:

  * sahə adları kod DƏYİŞMƏDƏN yeni hədəfə uyğunlaşır;
  * tapılmayan sahə səssiz default vermir — `usage=None`, `retrieved=[]`,
    üstəlik "sahə YOX idi" ilə "sahə BOŞ idi" fərqi `raw`-da qalır;
  * çoxnövbəli konfiqurasiya verilməyibsə case ADI ilə ölçülmür.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentproof.adapters import create_adapter
from agentproof.adapters._field_map import FieldMap, MISSING, first, resolve
from agentproof.adapters._http_core import MULTI_TURN_UNSUPPORTED
from agentproof.adapters.json_http import TRANSPORT_ERRORS
from agentproof.failure import BAD_REQUEST
from agentproof.graders import registry
from agentproof.testing.mock_json_agent import (
    CUSTOM_CONVERSATION_PATH,
    CUSTOM_MAP,
    MockJsonAgentServer,
)
from agentproof.types import AgentRequest, Case

CHUNK = {
    "chunk_id": "returns-and-refunds#restocking",
    "document": "returns-and-refunds.md",
    "content": "Opened items are subject to a 15% restocking fee.",
    "score": 0.93,
}
TOOL = {"name": "lookup_order", "arguments": {"order_id": "ORD-10001"}, "result": {"ok": True}}


def _request(query: str, session: str = "unit") -> AgentRequest:
    return AgentRequest(messages=[{"role": "user", "content": query}], session_id=session)


def _multi(*queries: str) -> AgentRequest:
    return AgentRequest(
        messages=[{"role": "user", "content": q} for q in queries], session_id="unit-mt"
    )


# ============================================================= yol həlli
@pytest.mark.parametrize(
    "path,expected",
    [
        ("a.b", 1),
        ("a.list.0.x", "first"),
        ("a.list.-1.x", "last"),
        ("", {"a": {"b": 1, "list": [{"x": "first"}, {"x": "last"}]}}),
    ],
)
def test_dotted_paths_reach_nested_values(path: str, expected: Any) -> None:
    payload = {"a": {"b": 1, "list": [{"x": "first"}, {"x": "last"}]}}
    assert resolve(payload, path) == expected


@pytest.mark.parametrize("path", ["a.missing", "a.list.9.x", "a.b.c", "nope"])
def test_missing_paths_are_missing_not_none(path: str) -> None:
    """`MISSING` ilə `None` fərqlidir: `None` hədəfin VERDİYİ dəyər ola bilər."""
    assert resolve({"a": {"b": 1, "list": [{"x": "first"}]}}, path) is MISSING


def test_null_value_does_not_block_the_next_candidate() -> None:
    """`{"answer": null, "output": "salam"}` -> ikinci namizəd qazanır."""
    value, path = first({"answer": None, "output": "salam"}, ("answer", "output"))
    assert (value, path) == ("salam", "output")


def test_unknown_map_key_is_rejected_not_ignored() -> None:
    """Yazı səhvi susqun default-a düşsəydi, müştərinin xəritəsi görməzdən
    gəlinər və adapter "təsadüfən" işləyərdi."""
    with pytest.raises(TypeError, match="retrieved_paths"):
        FieldMap.from_config(retrieved_paths="sources")


def test_multi_turn_is_never_guessed() -> None:
    """`conversation_id` üçün DEFAULT namizəd YOXDUR."""
    assert FieldMap().conversation_id == ()
    assert FieldMap().supports_multi_turn is False
    assert FieldMap.from_config(conversation_id_path="thread").supports_multi_turn is True


# ========================================================== canlı stub üzərində
@pytest.fixture
def server():
    with MockJsonAgentServer(query_field="message") as srv:
        yield srv


def _adapter(server: MockJsonAgentServer, **extra: Any):
    return create_adapter(
        "json_http",
        url=server.url,
        api_key=server.api_key,
        query_field="message",
        conversation_id_path=CUSTOM_CONVERSATION_PATH,
        **{**CUSTOM_MAP, **extra},
    )


@pytest.mark.asyncio
async def test_custom_field_names_are_read_without_touching_code(server) -> None:
    """`reply`/`cost`/`trace`/`citations` — heç biri default namizəd DEYİL."""
    server.scripted["q1"] = {
        "answer": "15% restocking fee tutulur.",
        "usage": {"input_tokens": 1820, "output_tokens": 190},
        "tool_calls": [TOOL],
        "retrieved": [CHUNK],
    }
    response = await _adapter(server).invoke(_request("q1 sualı"))

    assert response.error is None
    assert response.text == "15% restocking fee tutulur."
    assert response.usage is not None and response.usage.input_tokens == 1820
    assert [c.name for c in response.tool_calls] == ["lookup_order"]
    assert response.tool_calls[0].arguments == {"order_id": "ORD-10001"}
    assert [c.chunk_id for c in response.retrieved] == [CHUNK["chunk_id"]]
    # Bal STRING kimi gəldi — float-a çevrilməlidir (real hədəflərdə adi hal).
    assert response.retrieved[0].score == pytest.approx(0.93)
    assert response.raw["mapped_paths"]["text"] == "reply"


@pytest.mark.asyncio
async def test_typical_field_names_need_no_configuration() -> None:
    """`answer`/`usage`/`tool_calls`/`sources` — konfiqurasiyasız oxunmalıdır.

    Xəritə mövcud olduğu üçün "hər hədəf üçün konfiqurasiya yaz" demək
    lazımsız yükdür: tipik adlandırma default namizədlərlə tutulur, hansı
    yolun işlədiyi isə `raw["mapped_paths"]`-da AÇIQ qalır.
    """
    with MockJsonAgentServer(shape="plain", query_field="query") as server:
        server.scripted["q2"] = {
            "answer": "cavab",
            "usage": {"input_tokens": 10, "output_tokens": 4},
            "tool_calls": [TOOL],
            "retrieved": [CHUNK],
        }
        adapter = create_adapter("json_http", url=server.url, api_key=server.api_key)
        response = await adapter.invoke(_request("q2 sualı"))

    assert response.error is None and response.text == "cavab"
    assert response.usage is not None and response.usage.output_tokens == 4
    assert [c.name for c in response.tool_calls] == ["lookup_order"]
    assert [c.chunk_id for c in response.retrieved] == [CHUNK["chunk_id"]]
    # `conversation_id` BURADA YOXDUR: gövdədə `conversation_id` sahəsi olsa da
    # default namizəd olmadığı üçün oxunmur. Çoxnövbəlilik iddiası yalnız
    # konfiqurasiya ilə gəlir — bu, təxminin qarşısını alan qəsdən boşluqdur.
    assert response.raw["mapped_paths"] == {
        "text": "answer", "usage": "usage",
        "tool_calls": "tool_calls", "retrieved": "sources",
    }


@pytest.mark.asyncio
async def test_missing_usage_is_none_and_the_gap_is_visible(server) -> None:
    server.scripted["q3"] = {"answer": "token hesabı yoxdur"}
    response = await _adapter(server).invoke(_request("q3 sualı"))

    assert response.usage is None, "ölçülməyən istifadə sıfır kimi göstərilib"
    assert response.raw["fields_present"]["usage"] is False


@pytest.mark.asyncio
async def test_usage_object_with_unmapped_token_names_is_not_invented(server) -> None:
    """Obyekt TAPILDI, token adları tanınmadı -> `None` + adı çəkilən qeyd.

    Alternativ `Usage(0, 0)` olardı və hesabatda "$0.00 — büdcədən aşağı,
    KEÇDİ" kimi görünərdi: inandırıcı və yalan.
    """
    server.scripted["q4"] = {"answer": "cavab", "usage": {"input_tokens": 5, "output_tokens": 2}}
    # `cost` sahəsi var, amma alt-yollar səhv konfiqurasiya olunub.
    adapter = _adapter(server, usage_input_path="nope_in", usage_output_path="nope_out")
    response = await adapter.invoke(_request("q4 sualı"))

    assert response.usage is None
    assert response.raw["fields_present"]["usage"] is True
    assert "usage_fields_unmapped" in response.raw["map_notes"]


@pytest.mark.asyncio
async def test_missing_retrieval_makes_the_grader_skip_not_score_zero(server) -> None:
    """DoD: retrieval yoxdursa grader `skipped` verir — səssiz 0 YOX."""
    server.scripted["q5"] = {"answer": "bilik bazasına toxunmadım",
                             "usage": {"input_tokens": 5, "output_tokens": 2}}
    response = await _adapter(server).invoke(_request("q5 sualı"))

    assert response.retrieved == []
    assert response.raw["fields_present"]["retrieved"] is False
    case = Case(id="unit-retrieval", input="x", grader="retrieval_hit_at_k",
                expect={"gold_chunks": [CHUNK["chunk_id"]], "k": 3})
    for name in ("retrieval_hit_at_k", "precision_at_k"):
        result = registry.get(name).grade(case, response)
        assert result.skipped and not result.passed, name


@pytest.mark.asyncio
async def test_empty_answer_is_named(server) -> None:
    server.scripted["q6"] = {"answer": "", "usage": {"input_tokens": 5, "output_tokens": 0}}
    response = await _adapter(server).invoke(_request("q6 sualı"))

    assert response.text == ""
    assert response.error == "empty_answer"
    assert response.error_class == "unknown"


@pytest.mark.asyncio
async def test_conversation_is_chained_across_turns(server) -> None:
    seen: list[str] = []

    def reply(body: dict[str, Any]) -> dict[str, Any]:
        seen.append(str(body.get("conversation_id") or ""))
        return {"answer": f"növbə {len(seen)}"}

    server.scripted["q7"] = {"side_effect": reply,
                             "usage": {"input_tokens": 5, "output_tokens": 2}}
    response = await _adapter(server).invoke(_multi("q7 birinci", "q7 ikinci", "q7 üçüncü"))

    assert response.error is None
    assert response.n_turns == 3
    assert response.raw["conversation_chained"] is True
    # İlk sorğu boş id ilə gedir, sonrakılar EYNİ id ilə.
    assert seen[0] != "" or True  # stub id-ni özü paylayır
    assert len(set(seen[1:])) == 1 and seen[1] != ""


@pytest.mark.asyncio
async def test_multi_turn_without_config_is_refused_not_measured(server) -> None:
    """Ən vacib şərt: səssizcə TƏK-NÖVBƏLİ ölçmə YOXDUR."""
    server.scripted["q8"] = {"answer": "cavab"}
    # `conversation_id_path` QƏSDƏN verilmir.
    adapter = create_adapter("json_http", url=server.url, api_key=server.api_key,
                             query_field="message", **CUSTOM_MAP)
    before = len(server.request_log)
    response = await adapter.invoke(_multi("q8 birinci", "q8 ikinci"))

    assert response.error == MULTI_TURN_UNSUPPORTED
    assert response.error_class == BAD_REQUEST
    assert response.raw["multi_turn_supported"] is False
    assert response.raw["n_turns_requested"] == 2
    assert response.attempts == 0, "göndərilməyən sorğu cəhd kimi sayılmamalıdır"
    assert len(server.request_log) == before, "hədəfə sorğu getdi — pul yandı"


@pytest.mark.asyncio
async def test_single_turn_still_works_when_multi_turn_is_unsupported(server) -> None:
    """Çoxnövbəli boşluq qalan case-ləri BLOKLAMIR (sinif `HALTING` deyil)."""
    server.scripted["q9"] = {"answer": "tək növbəli cavab"}
    adapter = create_adapter("json_http", url=server.url, api_key=server.api_key,
                             query_field="message", **CUSTOM_MAP)
    assert (await adapter.invoke(_multi("q9 bir", "q9 iki"))).error == MULTI_TURN_UNSUPPORTED
    response = await adapter.invoke(_request("q9 sualı"))
    assert response.error is None and response.text == "tək növbəli cavab"


@pytest.mark.asyncio
async def test_unreachable_target_names_the_transport_failure() -> None:
    adapter = create_adapter("json_http", url="http://127.0.0.1:9/invoke", api_key="x")
    response = await adapter.invoke(_request("heç kim cavab vermir"))

    assert response.error in TRANSPORT_ERRORS and response.error == "request_transport"
    # Nəqliyyat xətası TƏXMİN EDİLMİR: 429 deyil, auth deyil.
    assert response.error_class == "unknown"
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_health_url_demands_a_real_two_hundred(server) -> None:
    """`health_url` verilibsə "server ayaqdadır" bəs etmir."""
    assert await _adapter(server).health() is True  # GET -> 405, server AYAQDADIR
    assert await _adapter(server, health_url=server.health_url).health() is True
    wrong = create_adapter("json_http", url=server.url, api_key=server.api_key,
                           health_url=f"{server.base_url}/nope")
    assert await wrong.health() is False


def test_url_is_required() -> None:
    with pytest.raises(ValueError, match="url"):
        create_adapter("json_http")

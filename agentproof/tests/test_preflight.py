"""AP-032 — preflight: hədəfin ölçüləbilirliyi.

Preflight-ın dəyəri BİR cümlədədir: *"sizin sistemdə bu 3 ölçü mümkün deyil,
çünki API bunları qaytarmır"*. Yəni sınanmalı olan da budur —

  * "hədəf vermir" (`no`) ilə "biz ölçə bilmədik" (`error`/`skipped`) qarışmır;
  * hər `no` üçün sıradan çıxan grader ailəsi ADI ilə yazılır;
  * `FIELD_GRADERS` registry ilə sinxron qalır — yeni grader unudulmur.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from agentproof.adapters import create_adapter
from agentproof.graders import registry
from agentproof.preflight import (
    ERROR,
    FIELD_GRADERS,
    NO,
    PROBE_FIELD,
    SKIPPED,
    YES,
    main,
    render_markdown,
    run_preflight,
)
from agentproof.testing.fake_graph import GRAPH_MAP, FakeSupportGraph
from agentproof.testing.mock_json_agent import (
    CUSTOM_CONVERSATION_PATH,
    CUSTOM_MAP,
    MockJsonAgentServer,
)

MEMO = "ORD-10001"
#: Qiymət cədvəlində OLAN model — `cost_under` yalnız onda qərar verə bilir.
PRICED_MODEL = "claude-sonnet-5"
# ⚠️ Cavabda MEMO QƏSDƏN YOXDUR: olsaydı, yaddaşsız hədəf də "nişanı
# xatırladı" kimi görünərdi və çoxnövbəli zond boş yaşıl olardı.
FULL = {
    "answer": "Opened items carry a 15% restocking fee; the order was delivered.",
    "usage": {"input_tokens": 1500, "output_tokens": 120},
    "tool_calls": [{"name": "lookup_order", "arguments": {"order_id": MEMO},
                    "result": {"ok": True}}],
    "retrieved": [{"chunk_id": "returns-and-refunds#restocking", "content": "...",
                   "score": 0.93, "document": "returns.md"}],
}


def _statuses(report) -> dict[str, str]:
    return {p.key: p.status for p in report.probes}


# ====================================================== registry ilə sinxron
def test_every_grader_is_tied_to_a_response_field():
    """Yeni grader HANSISA sahəyə bağlanmalıdır.

    Bağlanmasaydı, preflight sabah "hər şey ölçülür" deyər, halbuki hədəfin
    vermədiyi sahədən asılı bir ailə səssizcə `skipped` olardı — LIM-I09-un
    eynisi, sadəcə bir qat yuxarıda.
    """
    mapped = sorted({g for names in FIELD_GRADERS.values() for g in names})
    assert mapped == registry.names(), (
        "FIELD_GRADERS registry ilə uyğun deyil; "
        f"artıq: {sorted(set(mapped) - set(registry.names()))}, "
        f"çatmayan: {sorted(set(registry.names()) - set(mapped))}"
    )


def test_no_grader_is_counted_twice():
    flat = [g for names in FIELD_GRADERS.values() for g in names]
    assert len(flat) == len(set(flat))


def test_every_field_probe_maps_to_a_known_field():
    assert set(PROBE_FIELD.values()) <= set(FIELD_GRADERS)


# ============================================================== tam ölçüləbilir
@pytest.fixture
def server():
    with MockJsonAgentServer(query_field="query") as srv:
        yield srv


def _adapter(server: MockJsonAgentServer, **extra: Any):
    return create_adapter("json_http", url=server.url, api_key=server.api_key,
                          conversation_id_path=CUSTOM_CONVERSATION_PATH,
                          model=extra.pop("model", PRICED_MODEL),
                          **{**CUSTOM_MAP, **extra})


def _remembering(spec: dict[str, Any]) -> dict[str, Any]:
    """Yaddaşı olan hədəf: nişan yalnız zəncir qurulubsa xatırlanır."""
    memory: dict[str, list[str]] = {}

    def reply(body: dict[str, Any]) -> dict[str, Any]:
        conversation = str(body.get("conversation_id") or "")
        query = str(body.get("query", ""))
        turns = memory.setdefault(conversation, [])
        turns.append(query)
        known = next((t.split("ORD-")[1][:5] for t in turns if "ORD-" in t), None)
        if "Which order number" in query:
            return {"answer": f"You gave me ORD-{known}." if known else "Which order?"}
        return {}

    return {**spec, "side_effect": reply}


@pytest.mark.asyncio
async def test_a_fully_instrumented_target_loses_nothing(server) -> None:
    server.default = _remembering(FULL)
    report = await run_preflight(_adapter(server), target="json_http")

    assert _statuses(report) == {k: YES for k in
                                 ("health", "answer", "tool_calls", "retrieved",
                                  "usage", "cost", "multi_turn")}
    assert report.graders_lost == ()
    assert report.graders_unverified == ()
    assert report.graders_available == tuple(registry.names())
    assert report.latency_profile["samples"] >= 3


# ================================================== çatmayan sahələr ADLANIR
@pytest.mark.asyncio
async def test_a_target_without_retrieval_names_the_lost_graders(server) -> None:
    server.default = _remembering({k: v for k, v in FULL.items() if k != "retrieved"})
    report = await run_preflight(_adapter(server), target="json_http")

    assert _statuses(report)["retrieved"] == NO
    assert report.graders_lost == ("precision_at_k", "retrieval_hit_at_k")
    assert "retrieval_hit_at_k" not in report.graders_available

    markdown = render_markdown(report)
    assert "Retrieval parçaları görünür: XEYR" in markdown
    assert "`precision_at_k`, `retrieval_hit_at_k`" in markdown


@pytest.mark.asyncio
async def test_a_target_without_usage_kills_the_cost_grader(server) -> None:
    server.default = _remembering({k: v for k, v in FULL.items() if k != "usage"})
    report = await run_preflight(_adapter(server), target="json_http")

    assert _statuses(report)["usage"] == NO
    assert _statuses(report)["cost"] == NO
    assert "cost_under" in report.graders_lost
    assert "cost_under" in render_markdown(report)


@pytest.mark.asyncio
async def test_tokens_without_a_model_label_still_lose_the_cost_grader(server) -> None:
    """CANLI TAPINTI (Dify 1.17): `usage` gəlir, model adı gəlmir.

    Sahəyə baxmaqla "xərc ölçülür" demək olardı və hesabatdakı bütün
    `cost_under` sətirləri gözlənilmədən `skipped` çıxardı. Zond grader-in
    ÖZ qərarına baxdığı üçün bunu əvvəlcədən deyir.
    """
    server.default = _remembering(FULL)
    report = await run_preflight(_adapter(server, model=""), target="json_http")

    assert _statuses(report)["usage"] == YES, "token GƏLİR"
    assert _statuses(report)["cost"] == NO, "amma xərc hesablana bilmir"
    assert report.graders_lost == ("cost_under",)
    usage_row = report.by_key("usage")
    assert usage_row is not None and "model etiketi YOXDUR" in usage_row.detail


@pytest.mark.asyncio
async def test_a_target_without_tools_kills_the_tool_grader(server) -> None:
    server.default = _remembering({k: v for k, v in FULL.items() if k != "tool_calls"})
    report = await run_preflight(_adapter(server), target="json_http")

    assert _statuses(report)["tool_calls"] == NO
    assert report.graders_lost == ("tool_call_matches",)


@pytest.mark.asyncio
async def test_three_missing_fields_produce_the_sales_call_sentence(server) -> None:
    """Zəngdə deyilən cümlənin XAMMALI: üç sahə yoxdur -> dörd grader düşür."""
    server.default = _remembering({"answer": FULL["answer"]})
    report = await run_preflight(_adapter(server), target="json_http")

    assert [k for k, v in report.field_status.items() if v == NO] == [
        "tool_calls", "retrieved", "cost"
    ]
    assert report.graders_lost == (
        "cost_under", "precision_at_k", "retrieval_hit_at_k", "tool_call_matches"
    )


# =============================================== "ölçə bilmədik" != "vermir"
@pytest.mark.asyncio
async def test_a_dead_target_is_unmeasured_not_a_limitation() -> None:
    """Ən vacib fərq. `no` yazsaydıq, müştəriyə OLMAYAN məhdudiyyət danışardıq."""
    adapter = create_adapter("json_http", url="http://127.0.0.1:9/invoke", api_key="x")
    report = await run_preflight(adapter, target="json_http")

    statuses = _statuses(report)
    assert statuses["health"] == NO          # health HƏQİQƏTƏN "xeyr"dir
    assert statuses["answer"] == ERROR
    assert statuses["tool_calls"] == SKIPPED
    assert report.graders_lost == (), "ölçülməyən sahə məhdudiyyət kimi yazılıb"
    assert set(report.graders_unverified) == set(registry.names())
    assert "hədəfin məhdudiyyəti DEYİL" in render_markdown(report)


@pytest.mark.asyncio
async def test_multi_turn_refusal_is_reported_without_burning_requests(server) -> None:
    server.default = _remembering(FULL)
    # `conversation_id_path` verilmir -> adapter çoxnövbəlini ölçmür.
    adapter = create_adapter("json_http", url=server.url, api_key=server.api_key,
                             **CUSTOM_MAP)
    report = await run_preflight(adapter, target="json_http")

    multi = report.by_key("multi_turn")
    assert multi is not None and multi.status == NO
    assert multi.evidence["request_sent"] is False
    assert "Çoxnövbəli case-lər ölçülmür" in render_markdown(report)
    # Tək növbəli zond + çoxnövbəli imtina = CƏMİ bir sorğu.
    assert len(server.request_log) == 1


@pytest.mark.asyncio
async def test_a_broken_chain_is_a_no_not_a_silent_pass(server) -> None:
    """Zəncir qurulur, amma hədəf nişanı unudur -> `no` (kontekst itkisi C1)."""
    server.default = dict(FULL)  # yaddaş YOXDUR: hər növbə eyni cavabı verir
    report = await run_preflight(_adapter(server), target="json_http")

    multi = report.by_key("multi_turn")
    assert multi is not None and multi.status == NO
    assert multi.evidence["remembered"] is False


@pytest.mark.asyncio
async def test_skipping_multi_turn_is_declared_not_silent(server) -> None:
    server.default = _remembering(FULL)
    report = await run_preflight(_adapter(server), target="json_http", multi_turn=False)

    multi = report.by_key("multi_turn")
    assert multi is not None and multi.status == SKIPPED
    assert "ÖLÇÜLMƏMİŞ" in multi.detail
    assert len(server.request_log) == 1


# ============================================================ in-process hədəf
@pytest.mark.asyncio
async def test_preflight_works_against_an_in_process_target() -> None:
    """Preflight adapterdən ASILI DEYİL — `callable` hədəfi də ölçülür."""
    graph = FakeSupportGraph(default={
        "answer": f"Restocking fee is 15%; {MEMO} shipped.",
        "usage": {"input_tokens": 40, "output_tokens": 12},
    })
    report = await run_preflight(
        create_adapter("callable", fn=graph.answer, model=PRICED_MODEL, **GRAPH_MAP),
        target="callable",
    )

    statuses = _statuses(report)
    assert statuses["answer"] == YES and statuses["usage"] == YES
    # Bu qraf nə retrieval, nə tool qaytarır — hər ikisi ADI ilə düşür.
    assert statuses["retrieved"] == NO and statuses["tool_calls"] == NO
    assert report.graders_lost == (
        "precision_at_k", "retrieval_hit_at_k", "tool_call_matches"
    )
    assert "cost_under" in report.graders_available


# ==================================================================== CLI
def test_cli_writes_both_formats(tmp_path, capsys) -> None:
    md, js = tmp_path / "preflight.md", tmp_path / "preflight.json"
    code = main(["--target", "mock", "--no-multi-turn",
                 "--out-md", str(md), "--out-json", str(js)])

    # `mock` skriptsizdir -> cavab gəlmir -> qapı 1 qaytarır.
    assert code == 1
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert payload["target"] == "mock"
    assert payload["probes"][0]["probe"] == "health"
    assert "unmeasured_probes" in payload and "field_status" in payload
    assert md.read_text(encoding="utf-8").startswith("# Preflight")
    assert "# Preflight" in capsys.readouterr().out


def test_cli_can_emit_json_to_stdout(capsys) -> None:
    main(["--target", "mock", "--no-multi-turn", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["target"] == "mock"


def test_callable_target_cannot_be_built_from_the_cli() -> None:
    """Səssizcə boş adapter qurmaq əvəzinə səbəb deyilir."""
    with pytest.raises(SystemExit, match="Python"):
        main(["--target", "callable"])

"""AP-029 — refaktorun SÜBUTU: `full-run-03b` artefaktı yenidən emal olunur.

Canlı qaçış YOXDUR (başqa agent xərc həddindədir). Əvəzinə `reports/full-run-03b`
artefaktındakı 25 case-in QEYD OLUNMUŞ cavabından `mock_dify` skripti qurulur və
`dify_http` adapteri həmin məftil formatına qarşı yenidən qaçır. Yəni boru
xəttinin hamısı işləyir: HTTP -> SSE -> parsinq -> çoxnövbəli zəncir -> növbə
birləşməsi -> usage yığımı.

Gözlənti sadədir: **çıxan cavab artefaktdakının eynisi olmalıdır.** Refaktor
(AP-029) məntiqi başqa fayla köçürdü — davranışı DƏYİŞMƏDİ. Vahid testlər
hissələri ayrı-ayrı yoxlayır; bu fayl bütövü REAL qaçışın qeydinə tutur.

Artefakt `schema_version: 3`-dür (AP-024/AP-026-dan əvvəlki sahə dəsti) —
yəni test həm də köhnə artefaktın oxunmağa davam etdiyini sınayır.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from agentproof.adapters import create_adapter
from agentproof.testing.mock_dify import MockDifyServer
from agentproof.types import AgentRequest, AgentResponse

ARTIFACT = (
    Path(__file__).resolve().parents[2]
    / "reports/full-run-03b/o6zhCse2Dm4UV4r3njg4JB.json"
)


def _cases() -> list[dict[str, Any]]:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))["results"]


def _turns_of(response: dict[str, Any]) -> list[dict[str, Any]]:
    return response.get("turns") or [response]


def _spec(turn: dict[str, Any]) -> dict[str, Any]:
    """Qeyd olunmuş bir növbə -> stub-ın cavab təlimatı."""
    usage = turn.get("usage") or {}
    spec: dict[str, Any] = {
        "answer": turn.get("text", ""),
        "tool_calls": [
            {"name": t["name"], "arguments": t.get("arguments") or {}, "result": t.get("result")}
            for t in turn.get("tool_calls", [])
        ],
        "retrieved": [
            {
                "chunk_id": c.get("chunk_id", ""),
                "document": c.get("document", ""),
                "content": c.get("text", ""),
                "score": c.get("score", 0.0),
            }
            for c in turn.get("retrieved", [])
        ],
    }
    if usage:
        spec["usage"] = {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
        }
    else:
        # Ölçülməyən istifadə sıfır kimi göndərilmir — sahə ÜMUMİYYƏTLƏ gəlmir.
        spec["no_usage"] = True
    return spec


def _request(case: dict[str, Any]) -> AgentRequest:
    """Sorğu artefaktın özündən bərpa olunur: hər növbənin `raw.query`-si."""
    response = case["response"]
    messages = [
        {"role": "user", "content": t["raw"].get("query", "")} for t in _turns_of(response)
    ]
    # Skriptli `assistant` növbələri hədəfə göndərilmir, amma SAYILIR — say
    # artefaktda qeyd olunub, ona görə eyni sayda geri qoyulur.
    dropped = int(response["raw"].get("dropped_scripted_assistant_turns", 0) or 0)
    messages += [{"role": "assistant", "content": "(skript)"} for _ in range(dropped)]
    return AgentRequest(
        messages=messages, session_id=case["case_id"], metadata={"case_id": case["case_id"]}
    )


async def _replay_all(cases: list[dict[str, Any]]) -> dict[str, AgentResponse]:
    # Bütün 40 növbə sorğusu unikaldır -> BİR stub hamısına xidmət edir.
    by_query = {
        t["raw"].get("query", ""): _spec(t)
        for case in cases
        for t in _turns_of(case["response"])
    }

    def dispatch(body: dict[str, Any]) -> dict[str, Any]:
        return by_query.get(str(body.get("query", "")), {"answer": ""})

    out: dict[str, AgentResponse] = {}
    with MockDifyServer(scripted={"": {"side_effect": dispatch}}) as srv:
        adapter = create_adapter(
            "dify_http", base_url=srv.base_url, api_key=srv.api_key,
            model="claude-sonnet-5", backoff_base_s=0.01,
        )
        for case in cases:
            out[case["case_id"]] = await adapter.invoke(_request(case))
    return out


@pytest.fixture(scope="module")
def replayed() -> dict[str, AgentResponse]:
    return asyncio.run(_replay_all(_cases()))


def test_the_artifact_is_the_one_we_think_it_is():
    """Test BOŞ YAŞIL olmasın: artefakt yerində və gözlənilən ölçüdədir."""
    record = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert record["target"] == "dify_http"
    assert len(record["results"]) == 25
    assert sum(1 for r in record["results"] if r["response"]["raw"].get("multi_turn")) == 5


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["case_id"])
def test_recorded_case_is_reproduced_after_the_refactor(case, replayed):
    want = case["response"]
    got = replayed[case["case_id"]]

    assert got.text == want["text"]
    assert [t.name for t in got.tool_calls] == [t["name"] for t in want["tool_calls"]]
    assert [t.arguments for t in got.tool_calls] == [
        t.get("arguments") or {} for t in want["tool_calls"]
    ]
    assert [c.chunk_id for c in got.retrieved] == [c["chunk_id"] for c in want["retrieved"]]
    assert (got.usage is None) == (want["usage"] is None)
    if got.usage is not None:
        assert got.usage.input_tokens == want["usage"]["input_tokens"]
        assert got.usage.output_tokens == want["usage"]["output_tokens"]
    assert got.error == want.get("error")
    assert got.attempts == want.get("attempts", 1)
    assert len(got.turns) == len(want.get("turns", []))
    # Çoxnövbəli case zəncirlənmiş QALMALIDIR — refaktordan sonra da.
    if want["raw"].get("multi_turn"):
        assert got.raw["multi_turn"] is True
        assert got.raw["n_turns_sent"] == want["raw"]["n_turns_sent"]
        assert got.raw["conversation_chained"] == want["raw"]["conversation_chained"]
        assert got.raw["dropped_scripted_assistant_turns"] == (
            want["raw"]["dropped_scripted_assistant_turns"]
        )
        assert [t.text for t in got.turns] == [t["text"] for t in want["turns"]]

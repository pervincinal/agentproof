"""`target/corpus/anchors.py` — lövbər qatının şəbəkəsiz testləri.

Bu qat bloklayıcı problemi həll edir: retrieval gold-ları Dify segment
UUID-lərinə bağlı idi, yəni bilik bazası yenidən indeksləndikdə bütün
retrieval case-ləri SƏSSİZCƏ sınırdı. Burada iki şey qorunur:

1. Parse doğruluğu — segment mətnindən çıxarılan bənd açarları.
2. **Səssiz keçmə YOXDUR** — xəritə yoxdursa/köhnədirsə açıq xəta atılır.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from agentproof.types import Case
from target.corpus import anchors as A

MAP_PATH = Path(A.DEFAULT_MAP_PATH)


# ------------------------------------------------------------------ parse
def test_clause_keys_extracts_section_and_clauses():
    content = (
        "2. Standard return window\n"
        "2.1 The standard return window is **14 calendar days**.\n"
        "2.2 **Counting rule.** The delivery date counts as day 0.\n"
    )
    assert A.clause_keys(content) == ["2", "2.1", "2.2"]


def test_clause_keys_handles_appendix():
    content = (
        "Appendix A — Superseded provisions (v3.2)\n"
        "A.1 The standard return window is 30 calendar days.\n"
        "A.2 A restocking fee of 20% applies.\n"
    )
    assert A.clause_keys(content) == ["appendix-a", "appendix-a.1", "appendix-a.2"]


def test_clause_keys_ignores_prose_numbers():
    assert A.clause_keys("The fee is 9.90 AZN and applies always.") == []


def test_is_anchor_requires_md_suffix():
    assert A.is_anchor("returns-and-refunds.md#2.1")
    assert A.is_anchor("warranty-policy.md#appendix-a")
    # Köhnə/mock dataset-lərdəki sərbəst sətirlər lövbər SAYILMIR və toxunulmur.
    assert not A.is_anchor("returns-and-refunds#window")
    assert not A.is_anchor("5d00bd2a-1ed2-4206-b910-5e01e8d4b6b3")


# ------------------------------------------------------------------ qurma
def test_build_entries_keeps_first_segment_on_collision():
    docs = [{
        "id": "doc-1", "name": "x.md",
        "segments": [
            {"id": "seg-b", "position": 2, "content": "1.5 Later clause of section 1.\n"},
            {"id": "seg-a", "position": 1, "content": "1. Scope\n1.1 First clause.\n"},
        ],
    }]
    entries, collisions = A.build_entries(docs)
    assert entries["x.md#1"].segment_id == "seg-a"      # position 1 qalır
    assert entries["x.md#1.5"].segment_id == "seg-b"
    assert any("x.md#1" in c for c in collisions)


# --------------------------------------------------------------- səssiz keçmə yox
def test_missing_map_raises_explicitly(tmp_path):
    with pytest.raises(A.AnchorMapMissing) as exc:
        A.AnchorMap.load(tmp_path / "nope.json")
    assert "anchors.py build" in str(exc.value)


def test_unknown_anchor_raises_with_suggestions():
    amap = A.AnchorMap.load(MAP_PATH)
    with pytest.raises(A.AnchorResolutionError) as exc:
        amap.resolve("returns-and-refunds.md#99.9")
    assert "returns-and-refunds.md#2.1" in str(exc.value)  # yaxın variantlar göstərilir


def test_schema_version_mismatch_is_stale(tmp_path):
    raw = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    raw["schema_version"] = A.SCHEMA_VERSION + 1
    path = tmp_path / "anchor-map.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(A.AnchorMapStale):
        A.AnchorMap.load(path)


# ------------------------------------------------------------------ həll
def test_resolve_cases_rewrites_anchors_and_keeps_trace():
    case = Case(
        id="probe", input="q", grader="retrieval_hit_at_k",
        expect={"gold_chunks": ["returns-and-refunds.md#2.1"], "k": 4},
    )
    out = A.resolve_cases([case], MAP_PATH)[0]
    assert out.expect["gold_chunks"] != case.expect["gold_chunks"]
    assert out.expect["_gold_anchors"] == ["returns-and-refunds.md#2.1"]
    assert len(out.expect["gold_chunks"][0]) == 36  # UUID


def test_resolve_cases_passes_through_non_anchor_gold():
    case = Case(
        id="probe", input="q", grader="retrieval_hit_at_k",
        expect={"gold_chunks": ["5d00bd2a-1ed2-4206-b910-5e01e8d4b6b3"], "k": 3},
    )
    out = A.resolve_cases([case], MAP_PATH)[0]
    assert out.expect["gold_chunks"] == ["5d00bd2a-1ed2-4206-b910-5e01e8d4b6b3"]


def test_resolve_cases_without_gold_does_not_need_the_map(tmp_path):
    case = Case(id="probe", input="q", grader="contains_all", expect={"all": ["14"]})
    assert A.resolve_cases([case], tmp_path / "absent.json") == [case]


def test_active_and_superseded_clauses_map_to_different_segments():
    """R6-nın bütün mahiyyəti: cari bənd və Appendix A AYRI parçalardır."""
    amap = A.AnchorMap.load(MAP_PATH)
    active = amap.resolve("returns-and-refunds.md#2.1")
    stale = amap.resolve("returns-and-refunds.md#appendix-a.1")
    assert active != stale


def test_committed_map_covers_all_eight_policy_documents():
    amap = A.AnchorMap.load(MAP_PATH)
    docs = {e.document_name for e in amap.entries.values()}
    assert len(docs) == 8, docs
    for doc in docs:
        assert f"{doc}#appendix-a" in amap.entries, f"{doc}: Appendix A lövbəri yoxdur"


def test_map_entries_are_not_hand_edited():
    """Hər lövbər real segment id-yə (UUID) işarə etməlidir."""
    amap = A.AnchorMap.load(MAP_PATH)
    bad = [e.anchor for e in amap.entries.values() if len(e.segment_id) != 36]
    assert not bad, bad


def test_replace_keeps_case_frozen_semantics():
    case = Case(id="p", input="q", grader="contains_all", expect={"all": ["x"]})
    assert replace(case, expect={"all": ["y"]}).expect == {"all": ["y"]}
    assert case.expect == {"all": ["x"]}

"""AP-022 — lövbər xəritəsi ↔ CARİ dataset yoxlaması (A-19 reqressiyası).

A-19-da xəritə köhnə dataset-in (`e1471e22`) segment id-lərini saxlayırdı, app
isə `1623dd7e`-yə bağlı idi. Nəticə: 2 retrieval case-i `0/3` ilə sındı və
hesabatda «retrieval işləmir» kimi görünəcəkdi — halbuki retrieval gold bəndi
1-ci yerdə tapmışdı. Burada həmin mexanizmin bir daha səssiz qalmaması qorunur:

* uyğunsuz xəritə          -> qaçış DAYANIR (açıq xəta, `build` göstərilir)
* uyğun xəritə             -> keçir
* retrieval case-i yoxdur  -> blok YOXDUR (lazımsız maneə yaratmırıq)
* `--skip-anchor-check`    -> keçir, amma HESABATDA görünür
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentproof.report.pr_comment import anchor_block, anchor_line
from agentproof.runner.anchor_check import (
    AnchorCheck,
    AnchorMapMismatch,
    anchored_case_ids,
    retrieval_case_ids,
    verify_anchor_map,
)
from agentproof.types import Case, RunRecord
from target.corpus import anchors as A

LIVE = "1623dd7e-3e9e-4a8c-97c3-d66fdbac8e39"   # app-ın bağlı olduğu dataset
STALE = "e1471e22-0000-4000-8000-000000000000"  # A-19-dakı köhnə dataset
COMMITTED_MAP = Path(A.DEFAULT_MAP_PATH)


# ------------------------------------------------------------------ fikstur
def _map_with_dataset(tmp_path: Path, dataset_id: str) -> Path:
    raw = json.loads(COMMITTED_MAP.read_text(encoding="utf-8"))
    raw["dataset_id"] = dataset_id
    path = tmp_path / "anchor-map.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def _retrieval_case(case_id: str = "r2-hit-active-clause") -> Case:
    """`resolve_cases()`-dən SONRAKI forma: gold segment id, lövbər izi ayrıca."""
    return Case(
        id=case_id,
        input="What is the standard return window?",
        grader="retrieval_hit_at_k",
        expect={
            "gold_chunks": ["8a73270a-a6d8-452b-aa2f-fe0ff91adbaf"],
            "_gold_anchors": ["returns-and-refunds.md#2.1"],
            "k": 4,
        },
    )


def _plain_case(case_id: str = "text-01") -> Case:
    return Case(id=case_id, input="q", grader="contains_all", expect={"all": ["14"]})


def _record(check: AnchorCheck | None = None) -> RunRecord:
    record = RunRecord(
        run_id="r",
        target="dify_http",
        target_version="1.17.0",
        model="claude-sonnet-5",
        dataset_hash="abc",
        started_at="2026-08-28T00:00:00Z",
    )
    if check is not None:
        record.totals["anchor_check"] = check.to_dict()
    return record


# ------------------------------------------------------------- case seçimi
def test_retrieval_and_anchored_case_detection():
    cases = [_retrieval_case(), _plain_case()]
    assert retrieval_case_ids(cases) == ["r2-hit-active-clause"]
    assert anchored_case_ids(cases) == ["r2-hit-active-clause"]


def test_anchored_detection_works_before_resolution():
    """Yoxlama həlldən əvvəl də çağırıla bilər — xam lövbər tanınmalıdır."""
    case = Case(
        id="raw", input="q", grader="retrieval_hit_at_k",
        expect={"gold_chunks": ["returns-and-refunds.md#2.1"], "k": 4},
    )
    assert anchored_case_ids([case]) == ["raw"]


# ---------------------------------------------------------------- BLOKLAYIR
def test_stale_map_stops_the_run(tmp_path):
    """A-19-un birbaşa reqressiyası: xəritə başqa dataset-ə aiddir → dayan."""
    path = _map_with_dataset(tmp_path, STALE)
    with pytest.raises(AnchorMapMismatch) as exc:
        verify_anchor_map([_retrieval_case()], live_dataset_id=LIVE, map_path=path)
    message = str(exc.value)
    assert STALE in message and LIVE in message
    assert "anchors.py build" in message           # NƏ etmək lazım olduğunu deyir
    assert "--skip-anchor-check" in message
    assert exc.value.check.status == "mismatch"
    assert exc.value.check.n_retrieval_cases == 1


def test_mismatch_message_names_the_affected_cases(tmp_path):
    path = _map_with_dataset(tmp_path, STALE)
    cases = [_retrieval_case("r2-hit"), _retrieval_case("r2-precision"), _plain_case()]
    with pytest.raises(AnchorMapMismatch) as exc:
        verify_anchor_map(cases, live_dataset_id=LIVE, map_path=path)
    assert "r2-hit" in str(exc.value) and "r2-precision" in str(exc.value)
    assert exc.value.check.n_retrieval_cases == 2


def test_run_py_returns_1_on_mismatch(monkeypatch, tmp_path):
    """`evals/run.py` bu xətanı traceback-ə yox, təmiz exit koduna çevirir."""
    import evals.run as run_module

    path = _map_with_dataset(tmp_path, STALE)

    def with_stale_map(cases, **kwargs):
        # Yalnız xəritə yolu dəyişir — yoxlamanın ÖZÜ real funksiyadır.
        return verify_anchor_map(cases, **{**kwargs, "map_path": path})

    monkeypatch.setattr(run_module, "verify_anchor_map", with_stale_map)
    monkeypatch.setattr(run_module, "select_cases", lambda *a, **k: [_retrieval_case()])
    monkeypatch.setattr(run_module, "bind_judges", lambda *a, **k: [])
    monkeypatch.setattr(
        run_module, "probe_retrieval_config",
        lambda **k: run_module.RetrievalCheck(status="live", dataset_id=LIVE,
                                              dataset_source="app-config"),
    )
    code = run_module.main(
        ["--target", "mock", "--dataset", "evals/datasets/spike.jsonl", "--skip-model-check"]
    )
    assert code == 1


# ------------------------------------------------------------------ KEÇİR
def test_matching_map_passes(tmp_path):
    path = _map_with_dataset(tmp_path, LIVE)
    check = verify_anchor_map(
        [_retrieval_case()], live_dataset_id=LIVE, dataset_source="app-config", map_path=path
    )
    assert check.status == "match"
    assert check.verified and check.ok
    assert check.n_anchored_cases == 1
    assert LIVE[:8] in check.console_line()


def test_committed_map_matches_the_live_dataset():
    """Repo-dakı xəritə A-19-dan sonra düzəldilmiş dataset-ə baxır."""
    check = verify_anchor_map(
        [_retrieval_case()], live_dataset_id=LIVE, map_path=COMMITTED_MAP
    )
    assert check.status == "match"


# ------------------------------------------- retrieval case-i yoxdursa blok yox
def test_no_retrieval_cases_does_not_block(tmp_path):
    path = _map_with_dataset(tmp_path, STALE)  # BAYAT xəritə, amma əhəmiyyəti yoxdur
    check = verify_anchor_map(
        [_plain_case("a"), _plain_case("b")], live_dataset_id=LIVE, map_path=path
    )
    assert check.status == "no-retrieval"
    assert check.ok and not check.warnings
    assert check.n_retrieval_cases == 0


def test_missing_map_without_retrieval_cases_is_silent(tmp_path):
    check = verify_anchor_map([_plain_case()], live_dataset_id=LIVE,
                              map_path=tmp_path / "yoxdur.json")
    assert check.status == "no-retrieval"


# --------------------------------------------------------------- unverified
def test_unknown_live_dataset_warns_but_does_not_block(tmp_path):
    """Mock hədəf / Dify-sız CI: bloklamaq yoxlamanı söndürməyə məcbur edərdi."""
    path = _map_with_dataset(tmp_path, LIVE)
    check = verify_anchor_map([_retrieval_case()], live_dataset_id="", map_path=path)
    assert check.status == "unverified"
    assert check.ok and not check.verified
    assert check.warnings and "YOXLANMADI" in check.warnings[0]


def test_unreadable_map_with_raw_gold_ids_warns(tmp_path):
    """Xam segment id-li gold-lar da dataset dəyişəndə sınır — susmuruq."""
    case = Case(
        id="pilot-06", input="q", grader="retrieval_hit_at_k",
        expect={"gold_chunks": ["5d00bd2a-1ed2-4206-b910-5e01e8d4b6b3"], "k": 4},
    )
    check = verify_anchor_map([case], live_dataset_id=LIVE, map_path=tmp_path / "yox.json")
    assert check.status == "unverified"
    assert check.ok
    assert check.n_anchored_cases == 0
    assert check.warnings


# ------------------------------------------------------- --skip hesabata düşür
def test_skip_flag_passes_but_is_recorded():
    check = verify_anchor_map([_retrieval_case()], live_dataset_id=LIVE, skip=True)
    assert check.status == "skipped"
    assert check.ok
    assert check.warnings, "səssiz keçid olmamalıdır"
    assert "--skip-anchor-check" in check.warnings[0]
    assert "--skip-anchor-check" in check.console_line()


def test_skip_flag_does_not_load_the_map_but_still_counts_cases(tmp_path):
    check = verify_anchor_map(
        [_retrieval_case(), _plain_case()],
        live_dataset_id=LIVE,
        map_path=tmp_path / "yoxdur.json",
        skip=True,
    )
    assert check.status == "skipped"
    assert check.n_retrieval_cases == 1


def test_skip_surfaces_in_the_report():
    """AP-022 §4: bayraq işlədilibsə HESABATDA görünməlidir."""
    check = verify_anchor_map([_retrieval_case()], live_dataset_id=LIVE, skip=True)
    record = _record(check)

    line = anchor_line(record)
    assert "YOXLANILMADI" in line and "--skip-anchor-check" in line
    block = "\n".join(anchor_block(record))
    assert "Lövbər xəritəsi" in block and "--skip-anchor-check" in block


def test_report_line_for_each_status():
    def line(status: str, **kw) -> str:
        return anchor_line(_record(AnchorCheck(status=status, **kw)))

    assert "uyğun" in line("match", live_dataset_id=LIVE, n_anchored_cases=2)
    assert "tətbiq olunmur" in line("no-retrieval")
    assert "⚠️" in line("unverified", warnings=["canlı dataset id oxunmadı"])
    # Köhnə artefaktda sahə ümumiyyətlə yoxdur — bu da gizlədilmir.
    assert "QEYD OLUNMAYIB" in anchor_line(_record())


def test_clean_check_adds_no_noise_to_the_report():
    check = verify_anchor_map([_retrieval_case()], live_dataset_id=LIVE,
                              map_path=COMMITTED_MAP)
    assert anchor_block(_record(check)) == []


# ---------------------------------------------------------------- serializasiya
def test_to_dict_is_json_serialisable_and_complete():
    check = verify_anchor_map([_retrieval_case()], live_dataset_id=LIVE,
                              map_path=COMMITTED_MAP)
    payload = json.loads(json.dumps(check.to_dict(), ensure_ascii=False))
    assert payload["status"] == "match"
    assert payload["live_dataset_id"] == LIVE
    assert payload["map_dataset_id"] == LIVE
    assert payload["n_retrieval_cases"] == 1

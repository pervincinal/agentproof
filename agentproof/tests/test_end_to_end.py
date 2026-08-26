"""Ucdan-uca: dataset -> adapter -> Inspect -> grader -> RunRecord -> PR şərhi.

API açarı və real model çağırışı YOXDUR — hədəf mock Dify stub-udur.
Bu, R1 spike-ının regressiya testi kimi də işləyir (yol b).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from inspect_ai import eval as inspect_eval

from agentproof.report.baseline import compare, gate
from agentproof.report.normalize import normalize_log
from agentproof.report.pr_comment import render, render_console
from agentproof.runner.task import (
    apply_filter,
    build_task,
    dataset_hash,
    load_cases,
    select_cases,
)
from agentproof.testing.mock_dify import MockDifyServer, aurora_fixture

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "evals" / "datasets" / "spike.jsonl"


@pytest.fixture
def server():
    srv = MockDifyServer(scripted=aurora_fixture()).start()
    try:
        yield srv
    finally:
        srv.stop()


def _run(server: MockDifyServer, tmp_path: Path, **task_kw):
    task, cases = build_task(
        dataset_path=DATASET,
        adapter="dify_http",
        adapter_config={"base_url": server.base_url, "api_key": server.api_key},
        **task_kw,
    )
    logs = inspect_eval(
        task, model=None, log_dir=str(tmp_path / "logs"), display="none", log_level="error"
    )
    assert logs[0].status == "success", getattr(logs[0], "error", None)
    return normalize_log(logs[0], target="dify_http", target_version="1.17.0"), cases


# ------------------------------------------------------------ dataset qatı
def test_dataset_loads_five_cases():
    cases = load_cases(DATASET)
    assert len(cases) == 5
    assert {c.grader for c in cases} <= {
        "contains_all", "contains_none", "tool_call_matches",
        "retrieval_hit_at_k", "latency_under",
    }


def test_dataset_hash_is_stable_and_content_sensitive():
    cases = load_cases(DATASET)
    assert dataset_hash(cases) == dataset_hash(load_cases(DATASET))
    assert dataset_hash(cases) != dataset_hash(cases[:-1])


def test_filter_by_tag_and_severity():
    cases = load_cases(DATASET)
    assert {c.id for c in apply_filter(cases, "tag=gap")} == {
        "spike-02-giftcard-gap",
        "spike-03-giftcard-escalates",
    }
    assert all(c.severity == "high" for c in apply_filter(cases, "severity=high"))
    # fərqli açarlar VƏ məntiqi ilə birləşir
    assert {c.id for c in apply_filter(cases, "tag=budget,severity=low")} == {
        "spike-05-latency-budget"
    }


def test_unknown_filter_key_is_rejected():
    with pytest.raises(ValueError, match="naməlum filter"):
        apply_filter(load_cases(DATASET), "kateqoriya=policy")


# ------------------------------------------------------------- qaçış qatı
def test_full_run_grades_all_five_cases(server, tmp_path):
    record, cases = _run(server, tmp_path)
    assert len(record.results) == 5
    assert record.totals["n_passed"] == 5
    assert record.totals["pass_rate"] == 1.0
    assert record.dataset_hash == dataset_hash(cases)
    assert record.target_version == "1.17.0"


def test_run_issues_exactly_one_target_call_per_case(server, tmp_path):
    """R1 reqressiya mühafizəsi: yol (b) hədəfi çoxaltmır (yol (a) 5x çoxaldırdı)."""
    _run(server, tmp_path)
    assert len(server.request_log) == 5


def test_repeat_produces_k_responses_per_case(server, tmp_path):
    record, _ = _run(server, tmp_path, filter_expr="id=spike-01-restocking-fee", repeat=3)
    assert len(server.request_log) == 3
    assert record.results[0].attempt == 3


def test_broken_target_is_detected_not_silently_passed(server, tmp_path):
    """Hədəf yanlış siyasət rəqəmi verirsə case SINMALIDIR."""
    server.scripted["restocking"]["answer"] = "Qaytarma pəncərəsi 45 gündür, haqq 20%-dir."
    record, _ = _run(server, tmp_path, filter_expr="id=spike-01-restocking-fee")
    grade = record.results[0].grade
    assert not grade.passed
    assert not grade.skipped
    assert "15%" in grade.reason  # nəyin tapılmadığı hesabatda görünür


def test_cost_is_none_when_target_model_unknown(server, tmp_path):
    """Mock model adı vermir -> dollar hesablanmır; bu gizlədilmir."""
    record, _ = _run(server, tmp_path, filter_expr="id=spike-01-restocking-fee")
    assert record.totals["cost_usd"] == 0.0
    assert record.totals["price_table_as_of"]


def test_stage_filter_puts_all_deterministic_cases_in_cheap(server, tmp_path):
    record, _ = _run(server, tmp_path, stage="cheap")
    assert len(record.results) == 5
    # bütün grader-lər determinist olduğu üçün judge mərhələsi boşdur
    assert select_cases(DATASET, stage="judge") == []


def test_empty_selection_raises_instead_of_reporting_a_green_run():
    """Boş qaçış 100% keçmə kimi görünməməlidir."""
    with pytest.raises(ValueError, match="heç bir case seçmədi"):
        build_task(DATASET, adapter="mock", stage="judge")


# ------------------------------------------------------------ hesabat qatı
def test_baseline_diff_reports_change_not_absolute_number(server, tmp_path):
    baseline, _ = _run(server, tmp_path / "base")
    server.scripted["restocking"]["answer"] = "Qaytarma pəncərəsi 45 gündür, haqq 20%-dir."
    current, _ = _run(server, tmp_path / "cur")

    delta = compare(current, baseline)
    assert delta.broken == ["spike-01-restocking-fee"]
    assert delta.broken_high_severity == ["spike-01-restocking-fee"]
    assert delta.pass_rate_before == 1.0
    assert delta.pass_rate_after == 0.8

    gate_result = gate(delta)
    assert not gate_result.passed

    comment = render(delta, current, gate_result)
    assert "100% → 80%" in comment
    assert "spike-01-restocking-fee" in comment
    assert "bloklandı" in comment
    assert "15%" in comment  # sınan case-in tam səbəbi PR-da görünür


def test_run_record_round_trips_through_json(server, tmp_path):
    record, _ = _run(server, tmp_path)
    from agentproof.types import RunRecord

    restored = RunRecord.from_dict(json.loads(json.dumps(record.to_dict())))
    assert restored.totals == record.totals
    assert [r.case_id for r in restored.results] == [r.case_id for r in record.results]
    assert restored.results[0].grade.reason == record.results[0].grade.reason


def test_console_summary_is_readable_without_baseline(server, tmp_path):
    record, _ = _run(server, tmp_path)
    text = render_console(record)
    assert "keçdi" in text and "5/5" in text
    assert "skipped" in text  # skipped həmişə görünür, gizlənmir

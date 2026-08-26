"""Baseline diff və CI qapısı."""

from __future__ import annotations

from agentproof.report.baseline import GatePolicy, compare, gate
from agentproof.types import AgentResponse, CaseResult, GradeResult, RunRecord


def _case(case_id: str, passed: bool, severity: str = "medium", skipped: bool = False) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        response=AgentResponse(text="x"),
        grade=GradeResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            grader="contains_all",
            reason="ok" if passed else "tapılmadı",
            skipped=skipped,
        ),
        latency_ms=100,
        severity=severity,
    )


def _record(results: list[CaseResult], pass_rate: float, cost: float = 1.0,
            p95: float = 1000.0) -> RunRecord:
    return RunRecord(
        run_id="r",
        target="dify_http",
        target_version="1.17.0",
        model="claude-sonnet-5",
        dataset_hash="abc",
        started_at="2026-08-27T00:00:00Z",
        results=results,
        totals={"pass_rate": pass_rate, "cost_usd": cost, "p50_latency_ms": 500.0,
                "p95_latency_ms": p95},
    )


def test_compare_categorizes_fixed_broken_and_still_failing():
    baseline = _record([_case("a", True), _case("b", False), _case("c", False)], 1 / 3)
    current = _record([_case("a", False), _case("b", True), _case("c", False)], 1 / 3)
    delta = compare(current, baseline)
    assert delta.broken == ["a"]
    assert delta.fixed == ["b"]
    assert delta.still_failing == ["c"]


def test_compare_marks_flaky_and_does_not_call_it_a_regression():
    """PLAN.md qayda 1: təkrarlanmayan hal flaky-dir, reqressiya deyil."""
    baseline = _record([_case("a", True)], 1.0)
    current = _record([_case("a", True), _case("a", False)], 0.5)  # --repeat 2
    delta = compare(current, baseline)
    assert delta.flaky == ["a"]
    assert delta.broken == []


def test_compare_tracks_dataset_changes():
    baseline = _record([_case("a", True), _case("gone", True)], 1.0)
    current = _record([_case("a", True), _case("brand-new", False)], 0.5)
    delta = compare(current, baseline)
    assert delta.new_cases == ["brand-new"]
    assert delta.removed_cases == ["gone"]
    # yeni və dərhal sınan case reqressiya deyil, amma gizlənmir
    assert delta.broken == []
    assert "brand-new" in delta.still_failing


def test_skipped_only_case_is_not_counted_as_failure():
    baseline = _record([_case("a", False, skipped=True)], 0.0)
    current = _record([_case("a", False, skipped=True)], 0.0)
    delta = compare(current, baseline)
    assert delta.broken == [] and delta.still_failing == [] and delta.fixed == []


def test_gate_passes_when_nothing_regressed():
    delta = compare(_record([_case("a", True)], 1.0), _record([_case("a", True)], 1.0))
    assert gate(delta).passed


def test_gate_fails_on_high_severity_break():
    baseline = _record([_case("a", True, severity="high")], 1.0)
    current = _record([_case("a", False, severity="high")], 0.0)
    result = gate(compare(current, baseline))
    assert not result.passed
    assert any("high severity" in r for r in result.reasons)


def test_gate_fails_on_pass_rate_drop_beyond_threshold():
    baseline = _record([_case("a", True)], 0.91)
    current = _record([_case("a", True)], 0.87)
    result = gate(compare(current, baseline), GatePolicy(max_pass_rate_drop=0.02))
    assert not result.passed
    assert any("91.0%" in r and "87.0%" in r for r in result.reasons)


def test_gate_tolerates_drop_within_threshold():
    baseline = _record([_case("a", True)], 0.91)
    current = _record([_case("a", True)], 0.90)
    assert gate(compare(current, baseline), GatePolicy(max_pass_rate_drop=0.02)).passed


def test_gate_can_fail_on_cost_and_latency_budgets():
    baseline = _record([_case("a", True)], 1.0, cost=1.0, p95=1000.0)
    current = _record([_case("a", True)], 1.0, cost=2.0, p95=3000.0)
    delta = compare(current, baseline)
    result = gate(delta, GatePolicy(max_cost_increase_usd=0.5, max_p95_increase_ms=500))
    assert not result.passed
    assert len(result.reasons) == 2
    assert delta.cost_delta == 1.0

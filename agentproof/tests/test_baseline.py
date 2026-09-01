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


# ------------------------------------------------- AP-043: `--repeat` uyğunluğu
#
# REAL HADİSƏ. Baseline `--repeat 3` ilə qurulmuşdu; qapı `--repeat` OLMADAN
# (tək cəhd) qaçırıldı və heç bir xəbərdarlıq olmadan «77% → 100% · 1 düzəldi»
# yazdı. Hədəfin flaky nisbəti 19.8%-dir: TƏK cəhdin keçməsi heç nə sübut
# etmir — həmin case sadəcə bu dəfə keçmiş ola bilər. Yəni qapı «düzəldi»
# dedi, halbuki ola bilsin heç nə düzəlməyib. Bu, layihənin təkrarlanan
# problem sinfidir: ƏSASSIZ YAŞIL.

from agentproof.report.baseline import (  # noqa: E402
    check_repeat,
    declared_repeat,
    observed_repeat,
    repeat_of,
)
from agentproof.report.pr_comment import render, render_console  # noqa: E402


def _repeated(case_id: str, passed: bool, attempts: int) -> CaseResult:
    """`attempt` = case üçün alınmış müstəqil cavabların sayı (normalize.py)."""
    result = _case(case_id, passed)
    result.attempt = attempts
    return result


def _run(results: list[CaseResult], pass_rate: float, repeat: int | None = None) -> RunRecord:
    record = _record(results, pass_rate)
    if repeat is not None:
        record.totals["repeat"] = repeat
    return record


def test_fewer_repeats_than_baseline_is_flagged_and_claims_are_unverified():
    """Tək cəhdlik qaçış `--repeat 3` baseline-ı ilə müqayisə olunur."""
    baseline = _run([_repeated("a", False, 3)], 0.0, repeat=3)
    current = _run([_repeated("a", True, 1)], 1.0, repeat=1)

    delta = compare(current, baseline)

    assert delta.fixed == ["a"]  # müqayisə aparılır...
    assert delta.repeat_check.status == "fewer"
    assert delta.repeat_check.current == 1 and delta.repeat_check.baseline == 3
    assert not delta.verified  # ...amma iddia TƏSDİQLƏNMİR
    assert delta.repeat_check.warnings
    assert "--repeat 3" in delta.repeat_check.warnings[0]


def test_equal_repeat_produces_no_warning():
    baseline = _run([_repeated("a", False, 3)], 0.0, repeat=3)
    current = _run([_repeated("a", True, 3)], 1.0, repeat=3)

    delta = compare(current, baseline)

    assert delta.repeat_check.status == "match"
    assert delta.verified
    assert delta.repeat_check.warnings == []


def test_more_repeats_than_baseline_is_not_a_warning():
    """Daha çox təkrar = daha güclü ölçmə — iddia zəifləmir."""
    delta = compare(
        _run([_repeated("a", True, 5)], 1.0, repeat=5),
        _run([_repeated("a", False, 3)], 0.0, repeat=3),
    )
    assert delta.repeat_check.status == "more"
    assert delta.verified and delta.repeat_check.warnings == []


def test_unknown_baseline_repeat_is_explicit_not_a_silent_pass():
    """Ölçülə bilməyən baseline `1` sayılmır — NAMƏLUM olduğu açıq yazılır."""
    baseline = _run([], 0.0)  # nə elan var, nə nəticə — ölçmə yoxdur
    current = _run([_repeated("a", True, 1)], 1.0, repeat=1)

    delta = compare(current, baseline)

    assert delta.repeat_check.status == "unknown"
    assert delta.repeat_check.baseline is None
    assert delta.repeat_check.baseline_source == "unknown"
    assert not delta.verified
    assert "NAMƏLUM" in delta.repeat_check.warnings[0]
    assert "naməlum" in delta.repeat_check.detail


def test_repeat_is_measured_from_results_when_the_run_did_not_declare_it():
    """Köhnə artefaktda `totals["repeat"]` YOXDUR — `attempt` sahəsindən ölçülür."""
    old = _record([_repeated("a", True, 3)], 1.0)
    assert declared_repeat(old) is None
    assert observed_repeat(old) == 3
    assert repeat_of(old) == (3, "observed")

    delta = compare(_run([_repeated("a", True, 1)], 1.0, repeat=1), old)
    assert delta.repeat_check.status == "fewer"
    assert delta.repeat_check.baseline_source == "observed"


def test_declared_repeat_wins_over_the_observed_count():
    record = _run([_repeated("a", True, 1)], 1.0, repeat=3)
    assert repeat_of(record) == (3, "declared")


def test_broken_repeat_value_reads_as_unknown_not_as_one():
    for junk in (None, "", "üç", 0, -1, True):
        record = _record([], 1.0)
        record.totals["repeat"] = junk
        assert declared_repeat(record) is None, junk


def test_repeat_check_is_carried_into_the_artifact_dict():
    delta = compare(
        _run([_repeated("a", True, 1)], 1.0, repeat=1),
        _run([_repeated("a", False, 3)], 0.0, repeat=3),
    )
    payload = delta.to_dict()
    assert payload["verified"] is False
    assert payload["repeat_check"]["status"] == "fewer"
    assert payload["repeat_check"]["current"] == 1
    assert payload["repeat_check"]["baseline"] == 3
    assert payload["repeat_check"]["warnings"]


def test_repeat_mismatch_is_visible_in_pr_comment_and_console():
    baseline = _run([_repeated("a", False, 3)], 0.0, repeat=3)
    current = _run([_repeated("a", True, 1)], 1.0, repeat=1)
    delta = compare(current, baseline)

    markdown = render(delta, current)
    assert "TƏSDİQLƏNMƏMİŞ" in markdown.splitlines()[2]  # başlıq sətri
    assert "`--repeat` uyğunsuzluğu" in markdown
    assert "### 🟢 Düzələn (1) — ⚠️ TƏSDİQLƏNMƏMİŞ" in markdown
    assert "təkrar 1× (baseline 3×)" in markdown

    console = render_console(current, delta)
    assert "təkrar" in console and "TƏSDİQLƏNMƏMİŞ" in console
    assert "təsdiqlənməmiş" in console


def test_matching_repeat_leaves_the_report_unmarked():
    baseline = _run([_repeated("a", False, 3)], 0.0, repeat=3)
    current = _run([_repeated("a", True, 3)], 1.0, repeat=3)
    markdown = render(compare(current, baseline), current)
    assert "TƏSDİQLƏNMƏMİŞ" not in markdown
    assert "### 🟢 Düzələn (1)" in markdown


def test_gate_does_not_block_on_repeat_mismatch_by_default():
    delta = compare(
        _run([_repeated("a", True, 1)], 1.0, repeat=1),
        _run([_repeated("a", False, 3)], 0.0, repeat=3),
    )
    assert gate(delta).passed  # xəbərdarlıq var, bloklama yoxdur


def test_gate_can_be_told_to_block_on_repeat_mismatch():
    delta = compare(
        _run([_repeated("a", True, 1)], 1.0, repeat=1),
        _run([_repeated("a", False, 3)], 0.0, repeat=3),
    )
    result = gate(delta, GatePolicy(fail_on_repeat_mismatch=True))
    assert not result.passed
    assert "`--repeat` uyğunsuzluğu" in result.reasons[0]


def test_old_artifacts_without_repeat_still_compare():
    """Sxem <= 4 artefaktı `totals["repeat"]` saxlamır — oxuma sınmamalıdır."""
    old = RunRecord.from_dict(_record([_case("a", True)], 1.0).to_dict())
    delta = compare(old, old)
    assert delta.repeat_check.status == "match"  # hər ikisi 1× (ölçülən)
    assert delta.verified

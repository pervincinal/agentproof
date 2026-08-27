"""AP-007 — reproduksiya qapısının sayma məntiqi.

PLAN.md keyfiyyət qaydası #1: reproduksiya olunmayan tapıntı hesabata düşmür.
Bu testlər həmin qaydanın maşın tətbiqini qoruyur.
"""

from __future__ import annotations

from agentproof.report import reproduction as R
from agentproof.report.reproduction import (
    FLAKY,
    INCOMPLETE,
    SKIPPED,
    STABLE_FAIL,
    STABLE_PASS,
    UNSTABLE_FAIL,
    Attempt,
    classify_attempts,
    from_log_samples,
    from_records,
    render_text,
)
from agentproof.types import AgentResponse, Case, CaseResult, GradeResult, RunRecord


# ------------------------------------------------------------- köməkçilər
def _case(case_id: str, grader: str = "contains_all", needles=("alpha", "beta")) -> dict:
    return Case(
        id=case_id,
        input="sual",
        grader=grader,
        expect={"all": list(needles)},
        severity="high",
        tags=["policy"],
    ).to_dict()


def _resp(text: str, error: str | None = None) -> AgentResponse:
    return AgentResponse(text=text, error=error)


def _attempts(*flags: bool, reason: str = "sındı") -> list[Attempt]:
    return [
        Attempt(passed=f, skipped=False, reason="" if f else reason, grader="g")
        for f in flags
    ]


def _result(case_id: str, passed: bool, *, skipped=False, reason="sındı", attempt=1):
    return CaseResult(
        case_id=case_id,
        response=_resp("x"),
        grade=GradeResult(
            passed=passed, score=1.0 if passed else 0.0, grader="contains_all",
            reason="" if passed else reason, skipped=skipped,
        ),
        attempt=attempt,
        severity="high",
    )


def _record(results: list[CaseResult], run_id: str = "r1") -> RunRecord:
    return RunRecord(
        run_id=run_id, target="mock", target_version="1.0", model="m",
        dataset_hash="h", started_at="2026-08-27T00:00:00Z", results=results,
        totals={"pass_rate": 0.5},
    )


# --------------------------------------------- dörd əsas səbət (log mənbəyi)
def test_all_four_buckets_from_repeated_responses():
    """3 təkrarlı qaçış → stable-pass / stable-fail / flaky / skipped."""
    samples = [
        (_case("pass-3-3"), [_resp("alpha beta")] * 3),
        (_case("fail-3-3"), [_resp("yalnız alpha")] * 3),
        (_case("flaky-2-3"), [_resp("alpha beta"), _resp("alpha beta"), _resp("alpha")]),
        (_case("skip-3-3"), [_resp("", error="rate_limit")] * 3),
    ]
    report = from_log_samples(samples, source="sintetik")

    assert report.classifiable
    assert report.repeats == 3
    by_id = {v.case_id: v for v in report.verdicts}
    assert by_id["pass-3-3"].classification == STABLE_PASS
    assert by_id["fail-3-3"].classification == STABLE_FAIL
    assert by_id["flaky-2-3"].classification == FLAKY
    assert by_id["skip-3-3"].classification == SKIPPED

    assert by_id["fail-3-3"].n_failed == 3
    assert by_id["flaky-2-3"].n_passed == 2
    assert by_id["skip-3-3"].n_skipped == 3


def test_only_stable_fail_is_publishable():
    """FINDINGS.md yalnız stabil səbətdən qidalanır (AP-007 DoD)."""
    samples = [
        (_case("fail-3-3"), [_resp("yalnız alpha")] * 3),
        (_case("flaky-2-3"), [_resp("alpha beta"), _resp("alpha beta"), _resp("alpha")]),
        (_case("pass-3-3"), [_resp("alpha beta")] * 3),
    ]
    report = from_log_samples(samples)
    assert [v.case_id for v in report.findings] == ["fail-3-3"]
    assert report.to_dict()["publishable_case_ids"] == ["fail-3-3"]


# ------------------------------------------ tələb 3: eyni səbəblə sınmalıdır
def test_three_failures_with_different_reasons_are_not_stable_fail():
    """3/3 sındı, amma fərqli səbəblərlə → stabil tapıntı DEYİL."""
    samples = [
        (
            _case("mixed-reasons"),
            [_resp("alpha"), _resp("beta"), _resp("alpha")],
        )
    ]
    report = from_log_samples(samples)
    verdict = report.verdicts[0]
    assert verdict.classification == UNSTABLE_FAIL
    assert not verdict.publishable
    assert len(verdict.reason_variants) == 2
    assert "FƏRQLİ səbəb" in verdict.note


def test_three_failures_with_same_reason_are_stable_fail():
    samples = [(_case("same-reason"), [_resp("alpha"), _resp("alpha"), _resp("alpha")])]
    verdict = from_log_samples(samples).verdicts[0]
    assert verdict.classification == STABLE_FAIL
    assert verdict.publishable
    assert len(verdict.reason_variants) == 1


def test_reason_signature_ignores_only_whitespace_and_case():
    same = Attempt(False, reason="Tapılmayan  ifadə: ['beta']", grader="g")
    other = Attempt(False, reason="tapılmayan ifadə: ['beta']", grader="g")
    different = Attempt(False, reason="tapılmayan ifadə: ['alpha']", grader="g")
    assert same.signature == other.signature
    assert same.signature != different.signature


# --------------------------------------- tələb 4: təkrarsız qaçış susmur
def test_run_without_repeat_refuses_to_classify():
    """`--repeat` verilməyib → 'hamısı stabildir' DEYİL, açıq imtina."""
    report = from_records([_record([_result("a", True), _result("b", False)])])
    assert report.classifiable is False
    assert "TƏKRAR YOXDUR" in report.notice
    assert report.findings == []
    assert report.flaky_rate is None
    text = render_text(report)
    assert "TƏSNİFAT APARILMADI" in text
    assert "stable-pass" not in text


def test_collapsed_repeat_runrecord_is_not_read_as_stable():
    """`--repeat 3` RunRecord-da verdikt təkdir — bu, 3/3 sübutu deyil."""
    report = from_records([_record([_result("a", False, attempt=3)])])
    assert report.classifiable is False
    assert "BİRLƏŞDİRİB" in report.notice
    assert ".eval" in report.notice
    assert report.findings == []


def test_several_runrecords_are_classifiable():
    """Üç müstəqil qaçışın RunRecord-u → əsl 3 cəhd."""
    report = from_records(
        [
            _record([_result("a", True), _result("b", False)], run_id="r1"),
            _record([_result("a", True), _result("b", False)], run_id="r2"),
            _record([_result("a", False), _result("b", False)], run_id="r3"),
        ]
    )
    assert report.classifiable
    by_id = {v.case_id: v.classification for v in report.verdicts}
    assert by_id["a"] == FLAKY
    assert by_id["b"] == STABLE_FAIL


# ------------------------------------------- tələb 2: flaky nisbəti görünür
def test_flaky_rate_is_reported_and_alarms_above_threshold():
    samples = [(_case(f"pass-{i}"), [_resp("alpha beta")] * 3) for i in range(3)]
    samples.append(
        (_case("flaky"), [_resp("alpha beta"), _resp("alpha"), _resp("alpha beta")])
    )
    report = from_log_samples(samples)
    assert report.n_classified == 4
    assert report.flaky_rate == 0.25
    assert report.flaky_alarm is True
    text = render_text(report)
    assert "FLAKY NİSBƏTİ: 25.0%" in text
    assert "HƏDD" in text
    # nisbət ilk sətirlərdə görünür — hesabatın dibində gizlənmir
    assert "FLAKY NİSBƏTİ" in text.split("\n\n")[1]


def test_flaky_rate_is_none_not_zero_when_nothing_was_classified():
    """Heç nə ölçülməyəndə 0.0 qaytarmaq 'flaky yoxdur' kimi oxunardı."""
    report = from_log_samples([(_case("skip"), [_resp("", error="boom")] * 3)])
    assert report.flaky_rate is None
    assert "n/a" in render_text(report)


# ----------------------------------------------------- yarımçıq / xüsusi hallar
def test_partially_skipped_case_is_incomplete_not_stable():
    samples = [(_case("partial"), [_resp("alpha"), _resp("", error="rate_limit"), _resp("alpha")])]
    verdict = from_log_samples(samples).verdicts[0]
    assert verdict.classification == INCOMPLETE
    assert not verdict.publishable


def test_case_with_fewer_attempts_than_the_run_is_incomplete():
    samples = [
        (_case("full"), [_resp("alpha beta")] * 3),
        (_case("short"), [_resp("alpha beta")] * 2),
    ]
    by_id = {v.case_id: v.classification for v in from_log_samples(samples).verdicts}
    assert by_id["full"] == STABLE_PASS
    assert by_id["short"] == INCOMPLETE


def test_aggregate_grader_is_skipped_with_an_explicit_reason():
    """`consistency_at_k` k cavabı onsuz da tək verdiktə çevirir."""
    meta = Case(
        id="agg", input="s", grader="consistency_at_k", expect={"mode": "numbers"}
    ).to_dict()
    verdict = from_log_samples([(meta, [_resp("1"), _resp("2"), _resp("3")])]).verdicts[0]
    assert verdict.classification == SKIPPED
    assert "aqreqat" in verdict.note


def test_unknown_grader_is_skipped_not_counted_as_pass():
    meta = Case(id="x", input="s", grader="yoxdur_belə_grader").to_dict()
    verdict = from_log_samples([(meta, [_resp("a")] * 3)]).verdicts[0]
    assert verdict.classification == SKIPPED
    assert "grader tapılmadı" in verdict.note


# ------------------------------------------------------ birbaşa təsnifat
def test_classify_attempts_table():
    assert classify_attempts(_attempts(True, True, True), expected=3)[0] == STABLE_PASS
    assert classify_attempts(_attempts(False, False, False), expected=3)[0] == STABLE_FAIL
    assert classify_attempts(_attempts(True, False, True), expected=3)[0] == FLAKY
    assert classify_attempts([], expected=3)[0] == SKIPPED
    assert classify_attempts(_attempts(True), expected=1)[0] == INCOMPLETE


def test_json_output_is_machine_readable():
    samples = [
        (_case("fail-3-3"), [_resp("alpha")] * 3),
        (_case("flaky"), [_resp("alpha beta"), _resp("alpha"), _resp("alpha beta")]),
    ]
    data = from_log_samples(samples, source="sintetik").to_dict()
    assert data["classification_possible"] is True
    assert data["repeats"] == 3
    assert data["counts"][STABLE_FAIL] == 1
    assert data["counts"][FLAKY] == 1
    assert data["flaky_rate"] == 0.5
    assert data["publishable_case_ids"] == ["fail-3-3"]
    case = next(c for c in data["cases"] if c["case_id"] == "fail-3-3")
    assert case["n_attempts"] == 3 and case["n_failed"] == 3
    assert len(case["attempts"]) == 3
    assert case["publishable"] is True


def test_findings_gate_constant_is_stable_fail_only():
    assert R.PUBLISHABLE == (STABLE_FAIL,)

"""`report/html.py` — statik hesabatın müqavilə testləri (AP-012).

Burada yoxlanan şey "səhifə gözəl görünürmü" deyil. Hesabatın auditdə müdafiə
olunmasını təmin edən üç şərt maşınla yoxlanır:

  1. **Boş / natamam girişdə partlamır** — boş RunRecord, `usage`-siz case,
     baseline-siz, reproduksiya-sız qaçış.
  2. **Susmur.** Baseline, reproduksiya təsnifatı və judge kalibrasiyası
     yoxdursa bölmə YOX OLMUR, açıq xəbərdarlığa çevrilir. Auditdə bölmənin
     olmaması "problem yoxdur" kimi oxunur.
  3. **Kənara sorğu getmir və məzmun kod kimi icra olunmur** — CDN yoxdur,
     case mətnindəki HTML/skript escape olunur (dataset-də prompt injection
     yükləri var: escape olunmasa hesabatın özü hücum səthidir).
"""

from __future__ import annotations

import json
import re

import pytest

from agentproof.report import html as html_mod
from agentproof.report import reproduction as repro_mod
from agentproof.report.baseline import compare
from agentproof.types import (
    AgentResponse,
    CaseResult,
    GradeResult,
    RunRecord,
    ToolCall,
    Usage,
)


# ------------------------------------------------------------------ fixtures
def _result(
    case_id: str,
    passed: bool = True,
    skipped: bool = False,
    reason: str = "",
    grader: str = "regex_match",
    tags: list[str] | None = None,
    severity: str = "high",
    text: str = "cavab mətni",
    usage: bool = True,
) -> CaseResult:
    response = AgentResponse(
        text=text,
        usage=Usage(input_tokens=100, output_tokens=20, model="m") if usage else None,
        latency_ms=1500,
    )
    return CaseResult(
        case_id=case_id,
        response=response,
        grade=GradeResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            grader=grader,
            reason=reason or ("" if passed else "gözlənilən ifadə tapılmadı"),
            evidence={"pattern": "x"},
            skipped=skipped,
        ),
        cost_usd=0.01 if usage else None,
        latency_ms=1500,
        tags=tags if tags is not None else ["G2", "returns"],
        severity=severity,
    )


def _record(results: list[CaseResult] | None = None, **totals) -> RunRecord:
    results = results if results is not None else []
    graded = [r for r in results if not r.grade.skipped]
    base = {
        "n_cases": len(results),
        "n_graded": len(graded),
        "n_passed": sum(1 for r in graded if r.grade.passed),
        "n_failed": sum(1 for r in graded if not r.grade.passed),
        "n_skipped": len(results) - len(graded),
        "pass_rate": (sum(1 for r in graded if r.grade.passed) / len(graded)) if graded else 0.0,
        "cost_usd": sum(r.cost_usd or 0.0 for r in results),
        "p50_latency_ms": 1500.0,
        "p95_latency_ms": 1500.0,
        "judge": {"used": False},
        "lanes": 1,
    }
    base.update(totals)
    return RunRecord(
        run_id="RUN1",
        target="mock",
        target_version="1.0",
        model="test-model",
        dataset_hash="abc123",
        started_at="2026-08-27T10:00:00+00:00",
        results=results,
        totals=base,
    )


# ------------------------------------------------------ 1. natamam giriş
def test_empty_run_record_renders_without_error():
    """DoD: boş RunRecord-da render xəta vermir."""
    page = html_mod.render(_record([]))
    assert page.startswith("<!doctype html>")
    assert page.rstrip().endswith("</html>")
    assert "1 · Xülasə" in page


def test_empty_run_record_shows_na_not_zero_pass_rate():
    """Heç nə ölçülməyibsə «0%» yazmaq yalandır — n/a olmalıdır."""
    page = html_mod.render(_record([]))
    assert "n/a" in page


def test_case_without_usage_does_not_claim_zero_cost():
    page = html_mod.render(_record([_result("c1", usage=False)]))
    assert "naməlum sayır" in page


def test_render_survives_missing_totals_entirely():
    record = RunRecord(
        run_id="R",
        target="mock",
        target_version="",
        model="",
        dataset_hash="",
        started_at="",
        results=[_result("c1", passed=False)],
        totals={},
    )
    assert "<!doctype html>" in html_mod.render(record)


# ------------------------------------------------- 2. susmayan bölmələr
def test_missing_baseline_is_an_explicit_warning_not_a_silent_pass():
    page = html_mod.render(_record([_result("c1")]))
    assert "BASELINE YOXDUR" in page
    assert "REQRESSİYA YOXLANILMADI" in page


def test_baseline_delta_replaces_the_warning():
    current = _record([_result("c1", passed=False), _result("c2")])
    baseline = _record([_result("c1"), _result("c2")])
    page = html_mod.render(current, delta=compare(current, baseline))
    assert "BASELINE YOXDUR" not in page
    assert "Sındı" in page


def test_missing_reproduction_is_an_explicit_warning():
    page = html_mod.render(_record([_result("c1")]))
    assert "REPRODUKSİYA TƏSNİFATI YOXDUR" in page
    assert "ÖLÇÜLMƏDİ" in page  # flaky tile


def test_unclassifiable_reproduction_is_not_shown_as_stable():
    repro = repro_mod.ReproductionReport(
        verdicts=[],
        repeats=1,
        classifiable=False,
        notice="TƏKRAR YOXDUR",
    )
    page = html_mod.render(_record([_result("c1")]), repro=repro)
    assert "TƏSNİFAT APARILMADI" in page
    assert "TƏKRAR YOXDUR" in page


def test_flaky_alarm_is_visible_when_threshold_exceeded():
    verdicts = [
        repro_mod.CaseVerdict(
            case_id=f"c{i}",
            classification=repro_mod.FLAKY if i < 3 else repro_mod.STABLE_PASS,
            attempts=[
                repro_mod.Attempt(passed=bool(i % 2), grader="g", reason="r"),
                repro_mod.Attempt(passed=False, grader="g", reason="r"),
            ],
        )
        for i in range(10)
    ]
    repro = repro_mod.ReproductionReport(verdicts=verdicts, repeats=2)
    assert repro.flaky_alarm
    page = html_mod.render(_record([_result("c1")]), repro=repro)
    assert "HƏDD 10% AŞILDI" in page
    assert "FLAKY NİSBƏTİ" in page


def test_judge_section_is_mandatory_even_when_no_judge_grader_ran():
    page = html_mod.render(_record([_result("c1")]))
    assert 'id="judge"' in page
    assert "İŞLƏDİLMƏYİB" in page


def test_uncalibrated_judge_gets_an_uppercase_warning():
    record = _record(
        [_result("c1", grader="requires_justification")],
        judge={
            "used": True,
            "graders": ["requires_justification"],
            "calibrated": False,
            "warning": "kalibrasiya hesabatı yoxdur",
        },
    )
    page = html_mod.render(record)
    assert "KALİBRASİYA EDİLMƏMİŞ JUDGE" in page
    assert "MÜDAFİƏ" in page


def test_calibrated_judge_shows_agreement_kappa_and_n():
    record = _record(
        [_result("c1", grader="requires_justification")],
        judge={
            "used": True,
            "graders": ["requires_justification"],
            "calibrated": True,
            "passed": True,
            "agreement": 0.9666,
            "kappa": 0.9497,
            "kappa_interpretation": "çox güclü",
            "n": 30,
            "rubric": "requires_justification@v1",
            "judge_model": "claude-opus-5",
            "labels_sha256": "7580a521aa2f",
            "blocking_reasons": [],
            "summary": "uyğunluq 96.7% · κ 0.950 · n=30",
        },
    )
    page = html_mod.render(record)
    assert "96.7%" in page
    assert "0.950" in page  # κ
    assert ">30<" in page  # n
    assert "claude-opus-5" in page


def test_dry_run_calibration_is_flagged_as_unusable():
    record = _record(
        [_result("c1", grader="requires_justification")],
        judge={
            "used": True, "graders": ["requires_justification"], "calibrated": True,
            "passed": False, "agreement": 0.4, "kappa": 0.0, "n": 30,
            "dry_run": True, "summary": "s", "blocking_reasons": ["dry-run"],
        },
    )
    page = html_mod.render(record)
    assert "DRY-RUN" in page


def test_trend_needs_two_runs_on_the_same_dataset():
    record = _record([_result("c1")])
    other = _record([_result("c1")])
    other.run_id, other.dataset_hash = "RUN0", "DIFFERENT"
    page = html_mod.render(record, history=[other])
    assert "TREND QURULMADI" in page
    assert "müqayisə OLUNMUR" in page


def test_trend_line_is_drawn_for_two_comparable_runs():
    record = _record([_result("c1")])
    earlier = _record([_result("c1", passed=False)])
    earlier.run_id, earlier.started_at = "RUN0", "2026-08-26T10:00:00+00:00"
    page = html_mod.render(record, history=[earlier])
    assert "TREND QURULMADI" not in page
    assert "keçmə dərəcəsi trendi" in page


# ------------------------------------------- 3. təhlükəsizlik və offline
def test_no_external_resource_is_referenced():
    """Müştəri datası kənara çıxmır: CDN, şrift, piksel — heç nə."""
    page = html_mod.render(_record([_result("c1", passed=False)]))
    assert not re.search(r'(?:src|href)\s*=\s*"(?:https?:)?//', page)
    assert "@import" not in page
    assert not re.search(r"url\(\s*['\"]?(?:https?:)?//", page)
    assert "<link" not in page
    assert "fetch(" not in page and "XMLHttpRequest" not in page


def test_case_content_is_escaped_not_executed():
    """Dataset-də injection yükləri var — hesabat onları icra etməməlidir."""
    payload = '<script>alert("xss")</script><img src=x onerror=alert(1)>'
    record = _record(
        [_result("c1", passed=False, reason=payload, text=payload, tags=[payload])]
    )
    page = html_mod.render(record, case_inputs={"c1": payload})
    assert payload not in page
    assert "&lt;script&gt;" in page
    # səhifədə cəmi bir skript var: bizim öz filter kodumuz
    assert page.count("<script>") == 1


def test_full_input_and_output_are_present_for_failing_cases():
    long_answer = "AGENTİN TAM CAVABI " * 40
    record = _record([_result("c1", passed=False, text=long_answer)])
    page = html_mod.render(record, case_inputs={"c1": "İSTİFADƏÇİNİN TAM SUALI"})
    assert "İSTİFADƏÇİNİN TAM SUALI" in page
    assert long_answer.strip() in page
    assert "gözlənilən ifadə tapılmadı" in page


def test_passing_cases_are_not_expanded_only_failures_are():
    record = _record([_result("keçən"), _result("sınan", passed=False)])
    page = html_mod.render(record)
    assert 'data-case="sınan' in page.lower() or "sınan" in page
    assert page.count("<details data-case=") == 1


def test_multi_turn_responses_are_shown_turn_by_turn():
    result = _result("c1", passed=False)
    result.response.turns = [
        AgentResponse(text="birinci növbə", latency_ms=100),
        AgentResponse(text="ikinci növbə", latency_ms=200),
    ]
    page = html_mod.render(_record([result]))
    assert "birinci növbə" in page
    assert "ikinci növbə" in page
    assert "növbə-növbə" in page


def test_tool_calls_and_evidence_are_rendered_for_failing_cases():
    result = _result("c1", passed=False, grader="tool_call_matches")
    result.response.tool_calls = [ToolCall(name="issue_refund", arguments={"amount": 10})]
    page = html_mod.render(_record([result]))
    assert "issue_refund" in page
    assert "evidence" in page.lower()


def test_skipped_cases_are_listed_with_their_reason():
    skipped = _result("c1", passed=False, skipped=True, reason="usage yoxdur")
    page = html_mod.render(_record([skipped]))
    assert "usage yoxdur" in page
    assert "səssiz keçmə DEYİL" in page


# ------------------------------------------------------- aqreqasiya məntiqi
def test_pass_rate_denominator_excludes_skipped_cases():
    buckets = html_mod.by_grader(
        [
            _result("a", passed=True),
            _result("b", passed=False),
            _result("c", passed=False, skipped=True),
        ]
    )
    assert len(buckets) == 1
    b = buckets[0]
    assert (b.passed, b.failed, b.skipped, b.total) == (1, 1, 1, 3)
    assert b.pass_rate == pytest.approx(0.5)


def test_bucket_with_no_graded_case_reports_none_not_zero():
    b = html_mod.Bucket(key="x", skipped=3)
    assert b.pass_rate is None


def test_taxonomy_buckets_split_on_code_tags_only():
    results = [
        _result("a", tags=["G2", "returns"]),
        _result("b", passed=False, tags=["R6", "shipping"]),
        _result("c", tags=["returns"]),
    ]
    keys = {b.key for b in html_mod.by_taxonomy(results, {})}
    assert "G2" in keys and "R6" in keys
    assert "returns" not in keys
    assert "(kodsuz)" in keys  # taksonomiya kodu olmayan case gizlənmir


def test_taxonomy_labels_are_read_from_the_taxonomy_doc(tmp_path):
    doc = tmp_path / "tax.md"
    doc.write_text("### G1 — Siyasət uydurması (Policy fabrication) 🔴 №1\n", encoding="utf-8")
    assert html_mod.taxonomy_labels(doc)["G1"] == "Siyasət uydurması"


def test_taxonomy_labels_missing_doc_does_not_raise(tmp_path):
    assert html_mod.taxonomy_labels(tmp_path / "yoxdur.md") == {}


# --------------------------------------------------------- yükləmə köməkçiləri
def test_load_case_inputs_reads_ids_and_inputs(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text(
        '{"id":"a","input":"salam","grader":"g"}\n'
        "// şərh\n"
        "\n"
        '{"id":"b","input":[{"role":"user","content":"x"}],"grader":"g"}\n',
        encoding="utf-8",
    )
    inputs = html_mod.load_case_inputs(p)
    assert inputs["a"] == "salam"
    assert inputs["b"][0]["content"] == "x"


def test_load_records_skips_non_runrecord_json(tmp_path):
    (tmp_path / "junk.json").write_text('{"hello":1}', encoding="utf-8")
    (tmp_path / "run.json").write_text(
        json.dumps(_record([_result("c1")]).to_dict()), encoding="utf-8"
    )
    assert [r.run_id for r in html_mod.load_records([tmp_path])] == ["RUN1"]


def test_reproduction_report_round_trips_through_json():
    """Hesabat qapının verdiyi təsnifatı OXUYUR, yenidən hesablamır."""
    original = repro_mod.ReproductionReport(
        verdicts=[
            repro_mod.CaseVerdict(
                case_id="c1",
                classification=repro_mod.STABLE_FAIL,
                attempts=[repro_mod.Attempt(passed=False, grader="g", reason="r")] * 3,
                grader="g",
                severity="high",
                tags=["G2"],
            )
        ],
        repeats=3,
    )
    restored = repro_mod.report_from_dict(json.loads(json.dumps(original.to_dict())))
    assert restored.counts == original.counts
    assert restored.repeats == 3
    assert restored.verdicts[0].n_failed == 3
    assert restored.findings[0].case_id == "c1"


# ------------------------------------------------------------------- CLI
def test_cli_writes_index_html(tmp_path, capsys):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "rec.json").write_text(
        json.dumps(_record([_result("c1", passed=False)]).to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    assert html_mod.main([str(run_dir)]) == 0
    page = (run_dir / "index.html").read_text(encoding="utf-8")
    assert "BASELINE YOXDUR" in page
    assert "REQRESSİYA YOXLANILMADI" in capsys.readouterr().err


def test_cli_reads_reproduction_json_from_the_run_directory(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "rec.json").write_text(
        json.dumps(_record([_result("c1", passed=False)]).to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    repro = repro_mod.ReproductionReport(
        verdicts=[
            repro_mod.CaseVerdict(
                case_id="c1",
                classification=repro_mod.STABLE_FAIL,
                attempts=[repro_mod.Attempt(passed=False, grader="g", reason="r")] * 3,
            )
        ],
        repeats=3,
    )
    (run_dir / "reproduction.json").write_text(
        json.dumps(repro.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    assert html_mod.main([str(run_dir)]) == 0
    page = (run_dir / "index.html").read_text(encoding="utf-8")
    assert "REPRODUKSİYA TƏSNİFATI YOXDUR" not in page
    assert "stable-fail" in page


def test_cli_returns_error_when_no_run_record_found(tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    assert html_mod.main([str(tmp_path / "empty")]) == 2
    assert "RunRecord tapılmadı" in capsys.readouterr().err

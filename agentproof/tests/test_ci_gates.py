"""CI qapıları və CI xülasəsi (AP-011).

Workflow YAML-ında yazılmış məntiq test olunmur — ona görə qapılar
`evals/ci_gates.py` və `evals/ci_summary.py`-də yaşayır, testi də burada.
Hər qapının bilərəkdən KEÇƏN və bilərəkdən SINAN nümunəsi var: yalnız yaşıl
nümunəsi olan qapı, əslində, qapı deyil.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals import ci_gates, ci_summary  # noqa: E402

from agentproof.graders.calibration import CalibrationReport  # noqa: E402
from agentproof.types import (  # noqa: E402
    AgentResponse,
    CaseResult,
    GradeResult,
    RunRecord,
)


# ------------------------------------------------------------------ fixtures
def _result(case_id: str, passed: bool = True, reason: str = "", grader: str = "regex_match",
            skipped: bool = False) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        response=AgentResponse(text="x"),
        grade=GradeResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            grader=grader,
            reason=reason or ("" if passed else "ifadə tapılmadı"),
            skipped=skipped,
        ),
        cost_usd=0.01,
        latency_ms=100,
        tags=["G2"],
        severity="high",
    )


def _record(results=None, **totals) -> RunRecord:
    results = results if results is not None else [_result("c1")]
    base = {
        "n_cases": len(results),
        "n_graded": len(results),
        "n_passed": sum(1 for r in results if r.grade.passed),
        "n_failed": sum(1 for r in results if not r.grade.passed),
        "n_skipped": 0,
        "pass_rate": (sum(1 for r in results if r.grade.passed) / len(results)) if results else 0.0,
        "cost_usd": 0.01,
        "p50_latency_ms": 100.0,
        "p95_latency_ms": 100.0,
        "judge": {"used": False},
    }
    base.update(totals)
    return RunRecord(
        run_id="R1", target="mock", target_version="1.0", model="m",
        dataset_hash="hash1", started_at="2026-08-27T10:00:00+00:00",
        results=results, totals=base,
    )


def _write_run(tmp_path: Path, record: RunRecord) -> Path:
    d = tmp_path / "run"
    d.mkdir(exist_ok=True)
    (d / "rec.json").write_text(json.dumps(record.to_dict(), ensure_ascii=False), encoding="utf-8")
    return d


def _calibration(agreement=0.96, kappa=0.95, dry_run=False) -> CalibrationReport:
    return CalibrationReport(
        rubric_id="requires_justification",
        rubric_version="v1",
        judge_model="claude-opus-5",
        n=30,
        agreement=agreement,
        kappa=kappa,
        labels_sha256="deadbeef" * 8,
        confusion={},
        per_label_recall={},
        label_counts={},
        disagreements=[],
        dry_run=dry_run,
    )


# ------------------------------------------------------ kalibrasiya qapısı
def test_calibration_gate_is_not_applied_without_judge_cases():
    passed, msg = ci_gates.calibration_verdict([], None)
    assert passed
    assert "tələb olunmur" in msg


def test_calibration_gate_blocks_when_report_is_missing():
    passed, msg = ci_gates.calibration_verdict(["requires_justification"], None)
    assert not passed
    assert "KALİBRASİYA HESABATI YOXDUR" in msg


def test_calibration_gate_blocks_below_agreement_threshold():
    passed, msg = ci_gates.calibration_verdict(
        ["requires_justification"], _calibration(agreement=0.80)
    )
    assert not passed
    assert "BLOKLADI" in msg


def test_calibration_gate_blocks_on_low_kappa_even_with_high_agreement():
    """Xam faiz yüksək, κ aşağı — məhz κ-nın tutmalı olduğu hal."""
    passed, msg = ci_gates.calibration_verdict(
        ["requires_justification"], _calibration(agreement=0.90, kappa=0.10)
    )
    assert not passed
    assert "BLOKLADI" in msg


def test_calibration_gate_blocks_dry_run_report():
    passed, msg = ci_gates.calibration_verdict(
        ["requires_justification"], _calibration(dry_run=True)
    )
    assert not passed
    assert "DRY-RUN" in msg


def test_calibration_gate_passes_on_a_good_report():
    passed, msg = ci_gates.calibration_verdict(["requires_justification"], _calibration())
    assert passed
    assert "requires_justification" in msg


def test_judge_graders_are_detected_in_the_real_dataset():
    """Dataset-də judge case-i var — qapı boş yerə yaşıl olmasın."""
    judged = ci_gates.judge_graders_in(Path("evals/datasets/full.jsonl"))
    assert judged == ["requires_justification"]


def test_committed_calibration_report_passes_the_gate():
    """AP-011 DoD: qapı real repoda ən azı bir dəfə yaşıldır."""
    passed, _ = ci_gates.calibration_verdict(
        ci_gates.judge_graders_in(Path("evals/datasets/full.jsonl")),
        ci_gates.load_report(),
    )
    assert passed


# ---------------------------------------------------------- artefakt qapısı
def test_artifact_gate_accepts_a_complete_run_record():
    assert ci_gates.artifact_problems(_record()) == []


def test_artifact_gate_rejects_an_empty_run():
    problems = ci_gates.artifact_problems(_record([]))
    assert any("case nəticəsi yoxdur" in p for p in problems)


def test_artifact_gate_rejects_missing_provenance():
    record = _record()
    record.dataset_hash = ""
    assert any("provenans" in p for p in ci_gates.artifact_problems(record))


def test_artifact_gate_rejects_totals_that_disagree_with_results():
    assert any(
        "n_cases" in p for p in ci_gates.artifact_problems(_record(n_cases=99))
    )


def test_artifact_gate_rejects_a_failure_without_a_reason():
    record = _record()
    # `GradeResult.__post_init__` boş səbəbi bloklayır — qapı korlanmış
    # artefaktı (əl ilə redaktə, köhnə sxem) tutmalıdır, ona görə sahə
    # obyekt qurulduqdan sonra boşaldılır.
    record.results = [_result("c1", passed=False)]
    record.results[0].grade.reason = ""
    assert any("səbəbsiz" in p for p in ci_gates.artifact_problems(record))


def test_artifact_gate_rejects_a_missing_grader_name():
    record = _record([_result("c1", grader="")])
    assert any("grader adı" in p for p in ci_gates.artifact_problems(record))


def test_artifact_gate_rejects_a_halted_run():
    """AP-024: yarımçıq dayandırılmış qaçış CI-da YAŞIL çıxa bilməz.

    Qalan case-lər hədəfə ümumiyyətlə göndərilmədi — «hamısı keçdi» ilə
    «heç biri ölçülmədi» eyni şey deyil.
    """
    record = _record(
        halted={"halted": True, "reason": "credit_exhausted", "case_id": "c1", "detail": ""}
    )
    problems = ci_gates.artifact_problems(record)
    assert any("dayandırıldı" in p and "credit_exhausted" in p for p in problems)


def test_artifact_gate_passes_when_the_run_was_not_halted():
    record = _record(halted={"halted": False, "reason": "", "case_id": "", "detail": ""})
    assert ci_gates.artifact_problems(record) == []


def test_artifact_cli_returns_error_for_missing_run(tmp_path, capsys):
    assert ci_gates.main(["artifact", str(tmp_path / "yoxdur")]) == 1
    assert "boru xətti sındı" in capsys.readouterr().err


def test_artifact_cli_passes_on_a_written_run(tmp_path, capsys):
    assert ci_gates.main(["artifact", str(_write_run(tmp_path, _record()))]) == 0
    assert "RunRecord OK" in capsys.readouterr().out


# ---------------------------------------------------------- baseline qapısı
def test_baseline_gate_reports_missing_baseline_loudly(tmp_path, capsys, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    (tmp_path / "baselines").mkdir()

    assert ci_gates.main(["baseline", str(tmp_path / "baselines")]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == ""  # boş yol → `--baseline` ötürülmür
    assert "REQRESSİYA YOXLANILMADI" in captured.err
    assert "REQRESSİYA YOXLANILMADI" in summary.read_text(encoding="utf-8")


def test_baseline_gate_can_block_when_required(tmp_path):
    (tmp_path / "baselines").mkdir()
    assert ci_gates.main(["baseline", str(tmp_path / "baselines"), "--require"]) == 1


def test_baseline_gate_emits_the_path_when_a_snapshot_exists(tmp_path, capsys):
    d = tmp_path / "baselines"
    d.mkdir()
    (d / "mock@1.0.json").write_text("{}", encoding="utf-8")
    assert ci_gates.main(["baseline", str(d)]) == 0
    assert capsys.readouterr().out.strip().endswith("mock@1.0.json")


BASELINE_DIR = Path("evals/baselines")


def _repo_baselines() -> list[Path]:
    return sorted(BASELINE_DIR.glob("*.json"))


def test_repository_has_a_baseline_snapshot():
    """AP-013: `evals/baselines/` artıq BOŞ DEYİL.

    Bu testin əvvəlki versiyası qovluğun boş olduğunu yoxlayırdı və snapshot
    əlavə olunanda bilərəkdən qırmızı olurdu. Snapshot gəldi — indi eyni yer
    əks istiqaməti qoruyur: baseline TƏSADÜFƏN silinsə, CI reqressiya qapısı
    səssizcə söndürülərdi.
    """
    assert _repo_baselines(), (
        "evals/baselines/ boşdur — reqressiya qapısı işləmir. Snapshot "
        "`python evals/merge_runs.py ... --out evals/baselines/<ad>.json` ilə "
        "alınır (docs/BASELINE.md)."
    )


def test_repository_baseline_is_a_complete_run_record():
    """Baseline-da HƏR case üçün verdikt var — `skipped` qalmır.

    Ölçülməmiş case baseline-da qalsa, gələcək qaçışda o case reqressiya
    yoxlamasından səssizcə kənarda qalardı (AP-013 DoD).
    """
    for path in _repo_baselines():
        record = RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        assert ci_gates.artifact_problems(record) == [], path.name
        skipped = [r.case_id for r in record.results if r.grade.skipped]
        assert not skipped, f"{path.name}: ölçülməmiş case: {skipped[:5]}"
        ids = [r.case_id for r in record.results]
        assert len(ids) == len(set(ids)), f"{path.name}: təkrarlanan case_id"


def test_repository_baseline_gate_passes_with_require():
    """`--require` açıq olanda da qapı yaşıldır — CI-da bayraq qoşula bilər."""
    assert ci_gates.main(["baseline", str(BASELINE_DIR), "--require"]) == 0


def test_ci_workflow_requires_the_baseline_now_that_one_exists():
    """Snapshot var -> CI-da `--require` və `--fail-on-regression` AÇIQ olmalıdır.

    Bu qoşqu YAML-da yaşayır; testsiz qalsa, baseline əlavə olunandan sonra da
    CI baseline-sız yaşıl qalar və heç kim fərqinə varmazdı.
    """
    workflow = Path(".github/workflows/evals.yml").read_text(encoding="utf-8")
    assert "ci_gates.py baseline evals/baselines --require" in workflow
    assert "--fail-on-regression" in workflow


def test_baseline_gate_picks_the_newest_snapshot_by_timestamp_not_by_name(tmp_path, capsys):
    """Bir neçə snapshot olanda seçim TARİXƏ görədir (AP-042 ilə eyni qayda)."""
    d = tmp_path / "baselines"
    d.mkdir()
    (d / "zzz-old.json").write_text(
        json.dumps({"started_at": "2026-01-01T00:00:00+00:00"}), encoding="utf-8"
    )
    (d / "aaa-new.json").write_text(
        json.dumps({"started_at": "2026-08-28T00:00:00+00:00"}), encoding="utf-8"
    )
    assert ci_gates.main(["baseline", str(d)]) == 0
    assert capsys.readouterr().out.strip().endswith("aaa-new.json")


# ------------------------------------------------------------- CI xülasəsi
def test_summary_without_baseline_says_regression_was_not_checked():
    markdown, passed = ci_summary.build(_record(), None, "başlıq")
    assert passed  # bloklamaq üçün müqayisə lazımdır
    assert "BASELINE YOXDUR" in markdown
    assert "REQRESSİYA YOXLANILMADI" in markdown
    assert "başlıq" in markdown


def test_summary_with_baseline_shows_the_change_not_the_absolute_number():
    current = _record([_result("c1", passed=False), _result("c2")])
    baseline = _record([_result("c1"), _result("c2")])
    markdown, passed = ci_summary.build(current, baseline, "başlıq")
    assert "BASELINE YOXDUR" not in markdown
    assert "→" in markdown          # "100% → 50%"
    assert "sındı" in markdown
    assert not passed               # keçmə dərəcəsi düşdü → qapı bloklayır


def test_summary_gate_passes_when_nothing_regressed():
    record = _record([_result("c1"), _result("c2")])
    _, passed = ci_summary.build(record, _record([_result("c1"), _result("c2")]), "b")
    assert passed


def test_summary_includes_judge_block_when_judge_is_uncalibrated():
    record = _record(
        [_result("c1", grader="requires_justification")],
        judge={
            "used": True,
            "graders": ["requires_justification"],
            "calibrated": False,
            "warning": "KALİBRASİYA YOXDUR — nəticə müdafiə olunmur",
        },
    )
    markdown, _ = ci_summary.build(record, None, "b")
    assert "Judge kalibrasiyası" in markdown
    assert "KALİBRASİYA YOXDUR" in markdown


def test_summary_cli_writes_markdown_and_can_block(tmp_path, capsys):
    run_dir = _write_run(tmp_path, _record([_result("c1", passed=False)]))
    base = tmp_path / "base.json"
    base.write_text(
        json.dumps(_record([_result("c1")]).to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    out = tmp_path / "pr.md"
    code = ci_summary.main(
        [str(run_dir), "--baseline", str(base), "--out", str(out), "--fail-on-regression"]
    )
    assert code == 1
    assert "sındı" in out.read_text(encoding="utf-8")
    assert "REQRESSİYA" in capsys.readouterr().err


def test_summary_cli_warns_when_the_baseline_path_does_not_exist(tmp_path, capsys):
    run_dir = _write_run(tmp_path, _record())
    assert ci_summary.main([str(run_dir), "--baseline", str(tmp_path / "yox.json")]) == 0
    assert "REQRESSİYA YOXLANILMADI" in capsys.readouterr().err


def test_summary_cli_errors_when_no_run_record_exists(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(SystemExit):
        ci_summary.main([str(tmp_path / "empty")])


# ------------------------------------------------------------ workflow faylı
WORKFLOW = Path(".github/workflows/evals.yml")


def _workflow() -> dict:
    import yaml

    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_exists_and_parses():
    assert WORKFLOW.exists()
    assert set(_workflow()["jobs"]) == {"checks", "live"}


def test_cheap_stage_runs_on_every_pr_and_needs_no_secret():
    """Fork-dan gələn PR-da da qaçmalıdır — secret oxuyan addım OLMAMALIDIR."""
    wf = _workflow()
    checks = wf["jobs"]["checks"]
    assert checks["runs-on"] == "ubuntu-latest"
    assert "pull_request" in wf[True]  # PyYAML `on:`-u `True` kimi oxuyur
    raw = json.dumps(checks, ensure_ascii=False)
    assert "secrets." not in raw


def test_live_stage_is_manual_only_and_self_hosted():
    live = _workflow()["jobs"]["live"]
    assert live["if"] == "github.event_name == 'workflow_dispatch'"
    assert live["runs-on"] == ["self-hosted", "agentproof"]


def test_secrets_are_scoped_to_individual_steps_not_the_workflow():
    wf = _workflow()
    assert "env" not in wf, "workflow səviyyəsində env yoxdur (secret sızması riski)"
    for job in wf["jobs"].values():
        assert "env" not in job, "job səviyyəsində env yoxdur — secret addıma bağlanır"


def _workflow_code() -> list[str]:
    """Şərh sətirləri çıxarılmış YAML — yoxlama sənədin ÖZÜNÜ tutmasın."""
    return [
        line
        for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("#")
    ]


def test_no_step_echoes_a_secret_or_enables_shell_tracing():
    for line in _workflow_code():
        stripped = line.strip()
        assert "set -x" not in stripped, f"shell tracing açılıb: {stripped}"
        if "secrets." in stripped:
            assert not stripped.startswith("echo"), f"secret loga yazılır: {stripped}"
            assert "$GITHUB_STEP_SUMMARY" not in stripped


def test_pull_request_target_is_not_used():
    """Fork-dan gələn kod secret-li kontekstdə qaçırılmır."""
    assert not any("pull_request_target" in line for line in _workflow_code())


def test_workflow_documents_the_self_hosted_runner_requirement():
    """İşləməyən şeyi işləyirmiş kimi göstərmə qaydası."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "SELF-HOSTED RUNNER TƏLƏBİ" in text
    assert "self-hosted" in text


def test_cheap_stage_covers_the_required_checks():
    steps = " ".join(
        str(s.get("run", "")) + str(s.get("uses", ""))
        for s in _workflow()["jobs"]["checks"]["steps"]
    )
    assert "pytest" in steps
    assert "test_architecture_rule" in steps
    assert "build_full.py --check" in steps
    assert "--target mock" in steps
    assert "ci_gates.py calibration" in steps
    assert "ci_gates.py baseline" in steps
    assert "agentproof.report.html" in steps


def test_live_stage_verifies_the_anchor_map_and_the_reproduction_gate():
    steps = " ".join(str(s.get("run", "")) for s in _workflow()["jobs"]["live"]["steps"])
    assert "anchors.py verify" in steps
    assert "reproduce.py" in steps and "--fail-on-flaky" in steps

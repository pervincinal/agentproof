"""Judge kalibrasiyası — bilinən giriş → bilinən kappa. REAL API ÇAĞIRIŞI YOXDUR."""

from __future__ import annotations

import json
import math

import pytest

from agentproof.graders.calibration import (
    DEFAULT_LABELS_PATH,
    MIN_AGREEMENT,
    MIN_KAPPA,
    CalibrationReport,
    ConstantJudgeClient,
    ScriptedJudgeClient,
    agreement_rate,
    bias_probe,
    calibrate,
    cohens_kappa,
    confusion_matrix,
    judge_status,
    kappa_interpretation,
    load_labels,
    load_report,
    per_label_recall,
    save_report,
)
from agentproof.graders.judge import JudgeDecision

LABELS = load_labels(DEFAULT_LABELS_PATH)


# ------------------------------------------------------ bilinən giriş → kappa
def test_kappa_perfect_agreement():
    h = ["justified", "wrong", "unjustified", "justified"]
    assert cohens_kappa(h, list(h)) == pytest.approx(1.0)


def test_kappa_of_constant_judge_is_zero_even_when_percentage_looks_ok():
    """Xam faizin niyə kifayət etmədiyinin sübutu."""
    human = ["justified"] * 6 + ["wrong"] * 4
    judge = ["justified"] * 10
    assert agreement_rate(human, judge) == pytest.approx(0.6)
    assert cohens_kappa(human, judge) == pytest.approx(0.0)


def test_kappa_known_textbook_value():
    """Klassik 2x2: a=20, b=5, c=10, d=15 (n=50).

    po = 35/50 = 0.70
    pe = (25/50)(30/50) + (25/50)(20/50) = 0.30 + 0.20 = 0.50
    kappa = (0.70 - 0.50) / 0.50 = 0.40
    """
    human = ["justified"] * 25 + ["wrong"] * 25
    judge = ["justified"] * 20 + ["wrong"] * 5 + ["justified"] * 10 + ["wrong"] * 15
    assert agreement_rate(human, judge) == pytest.approx(0.70)
    assert cohens_kappa(human, judge) == pytest.approx(0.40)


def test_kappa_worse_than_chance_is_negative():
    human = ["justified", "justified", "wrong", "wrong"]
    judge = ["wrong", "wrong", "justified", "justified"]
    assert cohens_kappa(human, judge) < 0


def test_kappa_single_class_on_both_sides():
    assert cohens_kappa(["wrong"] * 5, ["wrong"] * 5) == pytest.approx(1.0)
    assert cohens_kappa(["wrong"] * 5, ["justified"] * 5) == pytest.approx(0.0)


def test_kappa_interpretation_bands():
    assert kappa_interpretation(0.1) == "zəif"
    assert kappa_interpretation(0.5) == "orta"
    assert kappa_interpretation(0.75) == "güclü"
    assert kappa_interpretation(0.9) == "çox güclü"


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        cohens_kappa(["justified"], ["justified", "wrong"])


def test_confusion_and_recall():
    human = ["justified", "justified", "wrong", "unjustified"]
    judge = ["justified", "wrong", "wrong", "justified"]
    m = confusion_matrix(human, judge)
    assert m["justified"]["justified"] == 1
    assert m["justified"]["wrong"] == 1
    recall = per_label_recall(human, judge)
    assert recall["justified"] == pytest.approx(0.5)
    assert recall["wrong"] == pytest.approx(1.0)
    assert recall["unjustified"] == pytest.approx(0.0)


# ------------------------------------------------------------------- dataset
def test_labeled_set_meets_the_minimum_size():
    assert len(LABELS) >= 25, "grader-eng.md: ən azı 25 əl ilə etiketlənmiş nümunə"


def test_every_sample_has_a_reason_for_its_label():
    assert all(s.note for s in LABELS.samples)


def test_dataset_covers_all_three_verdicts_with_usable_balance():
    counts = LABELS.label_counts
    assert set(counts) == {"justified", "unjustified", "wrong"}
    # Balans pozulubsa kappa qeyri-sabit olur — hər sinif ən azı 15%.
    assert min(counts.values()) / len(LABELS) >= 0.15


def test_dataset_contains_the_right_number_wrong_path_trap():
    """TRAPS.md §5: "30 gün" düz rəqəm, bayat yol."""
    trap = [s for s in LABELS.samples if s.label == "wrong" and "30 gün" in s.answer]
    assert trap, "korpusun əsas tələsi (T-01) dəstdə yoxdur"


def test_style_variants_exist_for_bias_probe():
    styles = {s.style for s in LABELS.samples}
    assert {"terse", "verbose", "confident", "hedged", "formatted"} <= styles


def test_broken_label_is_rejected_not_silently_dropped(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "rubric: requires_justification\n"
        "scenarios:\n  S: {question: q, answer_value: v, controlling_rule: r}\n"
        "samples:\n  - {id: X, scenario: S, answer: a, label: excellent, note: n}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="naməlum etiket"):
        load_labels(bad)


def test_label_without_note_is_rejected(tmp_path):
    bad = tmp_path / "nonote.yaml"
    bad.write_text(
        "rubric: requires_justification\n"
        "scenarios:\n  S: {question: q, answer_value: v, controlling_rule: r}\n"
        "samples:\n  - {id: X, scenario: S, answer: a, label: wrong, note: ''}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="note"):
        load_labels(bad)


# --------------------------------------------------------------- kalibrasiya
def _perfect_client() -> ScriptedJudgeClient:
    """Hər nümunənin İNSAN etiketini qaytaran mock → uyğunluq 100%."""
    return ScriptedJudgeClient({s.answer: s.label for s in LABELS.samples})


def test_perfect_judge_reaches_full_agreement_and_kappa():
    report = calibrate(_perfect_client(), LABELS)
    assert report.n == len(LABELS)
    assert report.agreement == pytest.approx(1.0)
    assert report.kappa == pytest.approx(1.0)
    assert report.passed
    assert report.blocking_reasons == []
    assert report.bias["n_flipped"] == 0


def test_dry_run_null_model_is_blocked_even_if_percentage_is_high():
    """Sabit verdiktli null model heç vaxt "kalibrasiya olunub" sayılmır."""
    report = calibrate(ConstantJudgeClient("unjustified"), LABELS, dry_run=True)
    assert report.n == len(LABELS)
    assert report.kappa == pytest.approx(0.0, abs=1e-9)
    assert not report.passed
    assert any("DRY-RUN" in r for r in report.blocking_reasons)


def test_agreement_below_threshold_blocks_and_names_the_rubric_rule():
    """85%-dən aşağı → RUBRİKA düzəlir, dataset yox. Mesaj bunu deməlidir."""
    flip = {"justified": "unjustified", "unjustified": "wrong", "wrong": "justified"}
    n_flip = 8
    mapping = {
        s.answer: (flip[s.label] if i < n_flip else s.label)
        for i, s in enumerate(LABELS.samples)
    }
    report = calibrate(ScriptedJudgeClient(mapping), LABELS)
    assert report.agreement < MIN_AGREEMENT
    assert not report.passed
    blocking = " ".join(report.blocking_reasons)
    assert "RUBRİKA" in blocking and "dataset yox" in blocking
    assert len(report.disagreements) == n_flip
    assert report.disagreements[0]["human_note"], "fikir ayrılığı insan qeydi ilə birlikdə"


def test_malformed_judge_output_is_counted_as_error_not_agreement():
    class Broken:
        model = "mock/broken"

        def complete(self, system, user, schema):
            from agentproof.graders.judge import JudgeRaw

            return JudgeRaw(text="{ bu json deyil")

    report = calibrate(Broken(), LABELS)
    assert report.n == 0
    assert len(report.errors) == len(LABELS)
    assert not report.passed


def test_thresholds_are_the_documented_ones():
    assert MIN_AGREEMENT == 0.85
    assert MIN_KAPPA == 0.70


# ------------------------------------------------------------------ yanlılıq
def test_bias_probe_flags_style_sensitivity():
    """Eyni məzmun, fərqli üslub → fərqli verdikt = verbosity/format yanlılığı."""
    mapping = {}
    for s in LABELS.samples:
        # Uzun cavablara sistematik olaraq daha yaxşı qərar verən "yanlı" judge
        mapping[s.answer] = "justified" if s.style == "verbose" else s.label
    report = calibrate(ScriptedJudgeClient(mapping), LABELS)
    assert report.bias["n_flipped"] > 0
    assert report.bias["by_style"]["verbose"]["deviations"] > 0
    assert report.bias["style_flip_rate"] > 0


def test_bias_probe_is_clean_for_style_blind_judge():
    report = calibrate(_perfect_client(), LABELS)
    assert report.bias["style_flip_rate"] == 0.0
    assert report.bias["findings"] == []


def test_bias_probe_documents_what_it_does_not_measure():
    report = calibrate(_perfect_client(), LABELS)
    joined = " ".join(report.bias["not_measured"])
    assert "position" in joined and "dil yanlılığı" in joined


def test_bias_probe_ignores_groups_without_style_variation():
    from agentproof.graders.calibration import LabeledSample

    same = [
        LabeledSample(id="a", scenario="S", answer="x", label="wrong", note="n", style="neutral"),
        LabeledSample(id="b", scenario="S", answer="y", label="wrong", note="n", style="neutral"),
    ]
    assert bias_probe(same, ["wrong", "justified"])["n_groups"] == 0


# ------------------------------------------------ hesabata avtomatik düşmə
def test_judge_status_reports_missing_calibration_loudly(tmp_path):
    status = judge_status(["requires_justification"], tmp_path / "yox.json")
    assert status["used"] and not status["calibrated"]
    assert "KALİBRASİYA EDİLMƏYİB" in status["warning"]


def test_judge_status_is_silent_when_no_judge_grader_used(tmp_path):
    assert judge_status(["contains_all", "cost_under"], tmp_path / "yox.json") == {"used": False}


def test_report_roundtrip_and_status_exposes_agreement_and_kappa(tmp_path):
    report = calibrate(_perfect_client(), LABELS)
    path = save_report(report, tmp_path / "report.json")
    again = load_report(path)
    assert again is not None
    assert again.agreement == pytest.approx(report.agreement)
    assert again.kappa == pytest.approx(report.kappa)

    status = judge_status(["requires_justification"], path)
    assert status["calibrated"] and status["passed"]
    assert status["agreement"] == pytest.approx(1.0)
    assert status["kappa"] == pytest.approx(1.0)
    assert "κ=" in status["summary"] and "uyğunluq" in status["summary"]


def test_markdown_report_always_shows_agreement_and_kappa():
    md = calibrate(_perfect_client(), LABELS).render_markdown()
    assert "uyğunluq" in md and "κ=" in md
    assert "| insan \\ judge |" in md


def test_report_json_is_serialisable_and_carries_the_rule():
    d = calibrate(_perfect_client(), LABELS).to_dict()
    payload = json.loads(json.dumps(d, ensure_ascii=False))
    assert payload["min_agreement"] == MIN_AGREEMENT
    assert "RUBRİKA" in payload["rule"]
    assert not math.isnan(payload["kappa"])
    assert payload["labels_sha256"] == LABELS.sha256


def test_dataset_hash_is_recorded_so_silent_edits_are_visible():
    report = CalibrationReport(
        rubric_id="requires_justification", rubric_version="v1", judge_model="m",
        n=1, agreement=1.0, kappa=1.0, labels_sha256=LABELS.sha256,
    )
    assert report.to_dict()["labels_sha256"] == LABELS.sha256


# ------------------------------------------------------------------- CLI
def test_cli_dry_run_writes_a_blocked_report(tmp_path, capsys):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "run_calibration",
        Path(__file__).resolve().parents[3] / "evals" / "calibration" / "run_calibration.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    out = tmp_path / "report.json"
    code = module.main(["--dry-run", "--out", str(out)])
    assert code == 0  # --fail-under-threshold verilməyib
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["dry_run"] is True
    assert written["passed"] is False
    assert written["n"] == len(LABELS)
    printed = capsys.readouterr().out
    assert "DRY-RUN" in printed and "κ=" in printed

    assert module.main(["--dry-run", "--out", str(out), "--fail-under-threshold"]) == 1


def test_cli_refuses_a_judge_weaker_than_the_sut(tmp_path):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "run_calibration2",
        Path(__file__).resolve().parents[3] / "evals" / "calibration" / "run_calibration.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError, match="güclü deyil"):
        module.main(
            ["--model", "claude-haiku-4-5", "--sut-model", "claude-opus-5",
             "--out", str(tmp_path / "r.json")]
        )


def test_scripted_client_returns_structured_decisions():
    client = ScriptedJudgeClient({"salam": JudgeDecision("wrong", "səbəb", 0.4)})
    raw = client.complete("s", "... salam ...", {})
    assert json.loads(raw.text)["verdict"] == "wrong"

"""Əl ilə transkript uydurma dəyər yazmır (AP-071).

Bu yolun bütün riski birdir: insan sorğu göndərəndə `usage`, gecikmə,
retrieval və tool izi YOXDUR. Onları sıfır yazmaq artefaktı «ölçdük, sıfır
çıxdı» kimi göstərərdi. Ölçmədik.

Qradersiz «tapıntı» isə sadəcə fikirdir, ona görə eyni qraderlər və eyni
təkrarlanma qapısı bu yolda da işləməlidir.
"""

from __future__ import annotations

import json
import subprocess
import sys
import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.import_manual import UNMEASURABLE, build, load_cases  # noqa: E402

DATASET = ROOT / "evals" / "datasets" / "full.jsonl"
CASE_OK = "bva-b-01-return_window_standard-13"
CASE_STALE = "r6a-t01-standard-window-value"


@pytest.fixture(scope="module")
def cases():
    return load_cases(DATASET)


def _transcript(responses):
    return {
        "target": "acme",
        "demo_url": "https://acme.example/demo",
        "tested_at": "2026-09-06",
        "tester": "tester",
        "responses": responses,
    }


def test_unmeasured_fields_are_none_not_zero(cases) -> None:
    rec = build(_transcript([
        {"case_id": CASE_OK, "attempt": 1, "text": "14 calendar days from the order date."},
    ]), cases)
    result = rec.results[0]
    assert result.cost_usd is None, "xərc sıfır yazılıb — ölçülmədi"
    assert rec.totals["cost_usd"] is None
    assert result.response.usage is None
    assert result.response.retrieved == []
    assert result.response.raw["measured"] is False


def test_writing_an_unmeasurable_field_is_refused(cases) -> None:
    for field in ("cost_usd", "latency_ms", "usage"):
        with pytest.raises(SystemExit) as e:
            build(_transcript([
                {"case_id": CASE_OK, "attempt": 1, "text": "x", field: 0},
            ]), cases)
        assert field in str(e.value)


def test_every_unmeasurable_field_is_guarded() -> None:
    """Siyahıya sahə əlavə olunmadan yeni sahə qəbul edilə bilməz."""
    assert set(UNMEASURABLE) == {
        "usage", "cost_usd", "latency_ms", "retrieved", "tool_calls",
    }


def test_manual_runs_are_distinguishable_from_automated_ones(cases) -> None:
    rec = build(_transcript([
        {"case_id": CASE_OK, "attempt": 1, "text": "14 calendar days from the order date."},
    ]), cases)
    assert rec.target.startswith("manual:")
    assert rec.totals["source"] == "manual_transcript"
    assert "ÖLÇÜLMƏYİB" in rec.totals["warning"]
    assert rec.model == "", "model naməlumdur — uydurulmamalıdır"


def test_the_real_graders_run_not_a_simplified_copy(cases) -> None:
    """Bayat dəyər qraderi burada da tutmalıdır."""
    rec = build(_transcript([
        {"case_id": CASE_STALE, "attempt": 1,
         "text": "The standard return window is 30 calendar days from delivery."},
    ]), cases)
    grade = rec.results[0].grade
    assert grade.passed is False
    assert "30" in json.dumps(grade.to_dict(), ensure_ascii=False)


def test_unknown_case_id_is_refused(cases) -> None:
    with pytest.raises(SystemExit, match="belə case yoxdur"):
        build(_transcript([{"case_id": "uydurma-case", "attempt": 1, "text": "x"}]), cases)


def test_missing_text_is_refused(cases) -> None:
    with pytest.raises(SystemExit, match="`text` yoxdur"):
        build(_transcript([{"case_id": CASE_OK, "attempt": 1}]), cases)


def test_empty_transcript_is_refused(cases) -> None:
    with pytest.raises(SystemExit, match="`responses` boşdur"):
        build(_transcript([]), cases)


def test_reproduction_gate_still_applies_end_to_end(tmp_path) -> None:
    """Tək cəhddən tapıntı ÇIXMIR — qapı əl ilə yolda da işləyir.

    `reproduce.py` bir cəhdlik case üçün 2 kodu qaytarır: «təsnifat mümkün
    deyil — FINDINGS üçün namizəd yoxdur». Bu, xəta deyil, qapının özüdür:
    bir dəfə sınayan şey stabil uğursuzluq sayıla bilməz.
    """
    tr = tmp_path / "t.yaml"
    tr.write_text(yaml.safe_dump(_transcript([
        {"case_id": CASE_STALE, "attempt": 1,
         "text": "The standard return window is 30 calendar days from delivery."},
    ]), allow_unicode=True))
    out = tmp_path / "run"

    subprocess.run(
        [sys.executable, "evals/import_manual.py", str(tr), "--out", str(out)],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    rerun = subprocess.run(
        [sys.executable, "evals/reproduce.py", str(out)],
        cwd=ROOT, capture_output=True, text=True,
    )

    assert rerun.returncode == 2, "bir cəhd namizəd sayılıb — qapı işləmir"
    assert "namizəd yoxdur" in rerun.stderr
    report = json.loads((out / "reproduction.json").read_text())
    flat = json.dumps(report, ensure_ascii=False)
    assert "incomplete" in flat
    assert CASE_STALE in flat


def test_three_matching_attempts_do_become_a_candidate(tmp_path) -> None:
    """Qapı hər şeyi rədd etmir — 3/3 eyni səbəb keçir."""
    text = "The standard return window is 30 calendar days from delivery."
    tr = tmp_path / "t.yaml"
    tr.write_text(yaml.safe_dump(_transcript([
        {"case_id": CASE_STALE, "attempt": i, "text": text} for i in (1, 2, 3)
    ]), allow_unicode=True))
    out = tmp_path / "run"

    subprocess.run(
        [sys.executable, "evals/import_manual.py", str(tr), "--out", str(out)],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    rerun = subprocess.run(
        [sys.executable, "evals/reproduce.py", str(out)],
        cwd=ROOT, capture_output=True, text=True,
    )

    assert rerun.returncode == 0, rerun.stderr
    report = json.loads((out / "reproduction.json").read_text())
    assert "stable-fail" in json.dumps(report, ensure_ascii=False)

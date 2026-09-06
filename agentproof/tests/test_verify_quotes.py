"""Müştəri sənədindəki agent sitatları artefaktdan gəlməlidir (AP-057).

Uydurulmuş və ya «səliqələnmiş» sitat müştəri hesabatında edilə biləcək ən
ağır səhvdir. Əl ilə köçürmə isə onu asanlaşdırır: bir söz düşür, bir tire
əlavə olunur, cümlə «yaxşılaşır» — və hesabatın qalanı da etibarını itirir.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "evals" / "verify_quotes.py"
DOCS = sorted((ROOT / "preaudit").glob("*/ONEPAGER*.md"))


def _run(doc: pathlib.Path, record: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(doc), str(record)],
        capture_output=True, text=True, cwd=ROOT,
    )


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.parent.name)
def test_every_quoted_answer_exists_in_the_artifact(doc: pathlib.Path) -> None:
    record = doc.parent / "merged" / "merged.json"
    if not record.exists():
        pytest.skip(f"{doc.parent.name}: birləşdirilmiş artefakt yoxdur")
    r = _run(doc, record)
    assert r.returncode == 0, r.stderr or r.stdout


def test_a_tidied_quote_is_caught(tmp_path) -> None:
    """Mühafizə həqiqətən tutur — sınaqla təsdiqlənir, iddia ilə yox."""
    record = tmp_path / "r.json"
    record.write_text(json.dumps({"results": [
        {"case_id": "c", "attempt": 1,
         "response": {"text": "You should report it within 24 hours."}}
    ]}))
    good = tmp_path / "good.md"
    good.write_text('| 1 | *"You should report it within 24 hours."* |\n')
    assert _run(good, record).returncode == 0

    tidied = tmp_path / "bad.md"
    tidied.write_text('| 1 | *"You should report it within 24 hours of the incident."* |\n')
    out = _run(tidied, record)
    assert out.returncode == 1
    assert "TAPILMADI" in out.stderr


def test_an_elided_quote_is_accepted_when_the_parts_are_real(tmp_path) -> None:
    record = tmp_path / "r.json"
    record.write_text(json.dumps({"results": [
        {"case_id": "c", "attempt": 1,
         "response": {"text": "Cancellation fees and time-on-cover charges may apply as per the TOBA."}}
    ]}))
    doc = tmp_path / "d.md"
    doc.write_text('| 1 | *"Cancellation fees … may apply as per the TOBA."* |\n')
    assert _run(doc, record).returncode == 0


def test_elision_cannot_reorder_the_source(tmp_path) -> None:
    """`…` boşluğu doldurur, cümləni yenidən düzmür."""
    record = tmp_path / "r.json"
    record.write_text(json.dumps({"results": [
        {"case_id": "c", "attempt": 1, "response": {"text": "Alpha then beta then gamma."}}
    ]}))
    doc = tmp_path / "d.md"
    doc.write_text('| 1 | *"gamma … alpha then beta"* |\n')
    assert _run(doc, record).returncode == 1

"""Saytdakı nümunə hesabat mənbədən geri qalmır və CSP-ni pozmur (AP-047).

İki risk var və hər ikisi səssizdir:

1. `EXAMPLE-client-report.md` dəyişir, `sample-report.html` qalır — alıcı
   köhnə sənədi oxuyur və biz bilmirik.
2. Render-ə qoyduğumuz siyasət inline stili və skripti bloklayır
   (`render.yaml`). Belə bir şey səhifəyə düşsə, brauzer **səssizcə** atır —
   nə xəta, nə log. Cədvəl düzləndirməsi itər, biz isə fərq etmərik.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BUILDER = ROOT / "site" / "build_sample.py"
OUTPUT = ROOT / "site" / "sample-report.html"


def test_built_page_is_in_sync_with_the_markdown() -> None:
    result = subprocess.run(
        [sys.executable, str(BUILDER), "--check"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_page_carries_nothing_the_content_policy_blocks() -> None:
    html = OUTPUT.read_text()
    assert not re.search(r"\sstyle=\"", html), "inline stil — CSP səssizcə atacaq"
    assert "<script" not in html, "script-src 'none'"
    assert "<style" not in html, "style-src inline-a icazə vermir"


def test_table_alignment_survived_the_conversion() -> None:
    """Inline stili silmək düzləndirməni ÖLDÜRMƏMƏLİDİR."""
    html = OUTPUT.read_text()
    assert 'class="ta-r"' in html
    css = (ROOT / "site" / "report.css").read_text()
    assert ".ta-r{text-align:right}" in css


def test_internal_note_is_not_published() -> None:
    """Mənbənin başındakı daxili şərh alıcıya getmir."""
    assert "<!--" in (ROOT / "docs" / "templates" / "EXAMPLE-client-report.md").read_text()
    body = OUTPUT.read_text().replace("<!DOCTYPE html>", "")
    assert "<!--" not in body


def test_the_report_is_reachable_from_the_site() -> None:
    for page in ("index.html", "rules.html"):
        assert '/sample-report' in (ROOT / "site" / page).read_text(), page


def test_report_still_discloses_that_the_client_is_synthetic() -> None:
    """Ən vacib cümlə: sifarişçi bizim qurduğumuz sistemdir."""
    html = OUTPUT.read_text()
    assert "Aurora Goods" in html
    assert "sınaq üçün" in html or "we built ourselves" in html

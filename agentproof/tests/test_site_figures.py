"""Saytda dərc olunan hər rəqəm artefaktdan yoxlanılır.

NİYƏ VAR (AP-070). `site/index.html` ictimai səhifədir və orada altı rəqəm
dərc olunur. Onlardan biri — dataset ölçüsü — **şişirdilmiş** dərc olundu:
`full.jsonl`-ın sətirləri sayıldı, halbuki faylın başında 7 şərh sətri var,
yəni 185 case 192 kimi göstərildi. Səhv özü kiçikdir; problem odur ki, onu
**heç nə yoxlamırdı**. Auditor saytında yoxlanmayan rəqəm, hesabatda
təkrarlanmayan tapıntı ilə eyni şeydir.

Bu test hər rəqəmi öz artefaktına bağlayır. Yeni rəqəm əlavə olunub burada
qeydiyyatdan keçmirsə, test SINIR — yəni mühafizəsiz rəqəm dərc oluna bilmir.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SITE = ROOT / "site" / "index.html"

# Saytdakı `<div class="fig">` blokunun dəyəri -> onu doğrulayan funksiya.
# Açar səhifədəki mətnin EYNİSİDİR (normallaşdırılmış boşluqla).


def _dataset_cases() -> int:
    """`full.jsonl`-dakı case sayı — şərh sətirləri SAYILMIR."""
    n = 0
    for line in (ROOT / "evals" / "datasets" / "full.jsonl").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        json.loads(line)  # sətir JSON deyilsə burada sınsın
        n += 1
    return n


def _limitations() -> int:
    text = (ROOT / "docs" / "LIMITATIONS.md").read_text()
    return len(set(re.findall(r"^### (LIM-[A-Z]\d+)", text, re.M)))


def _findings() -> int:
    text = (ROOT / "FINDINGS.md").read_text()
    return len(set(re.findall(r"^### (F-\d+)", text, re.M)))


def _conformance_checks() -> int:
    text = (ROOT / "agentproof" / "adapters" / "conformance.py").read_text()
    return len(re.findall(r"^async def _check_", text, re.M))


def _calibration() -> dict:
    return json.loads((ROOT / "evals" / "calibration" / "report.json").read_text())


def _figures() -> list[tuple[str, str]]:
    """Səhifədəki (dəyər, izah) cütlərini oxuyur."""
    html = SITE.read_text()
    pairs = re.findall(
        r'<div class="fig"><div class="v">(.*?)</div><div class="k">(.*?)</div></div>',
        html,
        re.S,
    )
    clean = lambda s: re.sub(r"<[^>]+>|&nbsp;|\s+", lambda m: " " if m.group(0) in ("&nbsp;",) or m.group(0).isspace() else "", s).strip()
    return [(clean(v), clean(k)) for v, k in pairs]


def test_site_has_the_expected_number_of_figures() -> None:
    assert len(_figures()) == 6, "sayta rəqəm əlavə/silinib — bu testi yenilə"


def test_dataset_size_is_not_overstated() -> None:
    value = dict(_figures())["185"]
    assert "graded cases" in value
    assert _dataset_cases() == 185


def test_limitation_count_matches_the_document() -> None:
    assert "44" in dict(_figures())
    assert _limitations() == 44


def test_finding_count_matches_the_register() -> None:
    assert "4" in dict(_figures())
    assert _findings() == 4


def test_conformance_check_count_matches_the_suite() -> None:
    assert "25" in dict(_figures())
    assert _conformance_checks() == 25


def test_judge_calibration_figures_match_the_report() -> None:
    report = _calibration()
    assert report["judge_model"] != "dry-run/constant", "dry-run rəqəmi dərc olunmur"
    assert round(report["agreement"] * 100, 1) == 96.7
    assert round(report["kappa"], 2) == 0.95
    figures = dict(_figures())
    assert "96.7%" in figures
    assert "0.95" in figures["96.7%"]


def test_every_published_figure_is_guarded() -> None:
    """Mühafizəsiz rəqəm dərc oluna bilməz."""
    guarded = {"185", "29 → 5", "96.7%", "44", "25", "4"}
    published = {v for v, _ in _figures()}
    unguarded = published - guarded
    assert not unguarded, f"bu rəqəmləri heç nə yoxlamır: {sorted(unguarded)}"


# Sürüşən rəqəm README-dən çıxarıldı: test sayı hər commit-də dəyişir,
# ona görə orada rəqəm YOXDUR. Bu test köhnə iddiaların qayıtmamasını qoruyur.
@pytest.mark.parametrize("claim", ["150 cases", "1278 tests", "1329 tests", "192"])
def test_readme_carries_no_stale_count(claim: str) -> None:
    assert claim not in (ROOT / "README.md").read_text()

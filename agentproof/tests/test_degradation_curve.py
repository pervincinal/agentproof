"""AP-017 — çoxnövbəli deqradasiya əyrisi (`failure-onset turn`).

DÖRD ŞEY QORUNUR:

1. **Ailə dizaynı: yeganə dəyişən MƏSAFƏDİR.** Eyni ailənin bütün üzvlərində
   faktlar, sual və iynə SÖZBƏSÖZ eynidir; yalnız aradakı məzmunsuz növbələrin
   sayı dəyişir. Bu pozularsa, ölçdüyümüz kontekst məsafəsi deyil, başqa bir
   şey olur — və rəqəm izah edilə bilməz.
2. **Doldurucular MƏLUMAT DAŞIMIR.** Daşısaydılar, ölçü məsafə deyil, məlumat
   həcmi olardı.
3. **Assertion A-01…A-26 dərslərinə uyğundur:** çılpaq rəqəm iynəsi yoxdur,
   pattern-lər auditdən keçmiş MAKROLARDIR (yenidən icad edilmir).
4. **Analizator ölçülməmişi «sınmadı» yazmır.** İnfrastruktur xətası ilə sıfır
   sınma arasındakı fərq hesabatın ən vacib fərqidir.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
BUILDER = REPO / "evals" / "datasets" / "build_full.py"
DATASET = REPO / "evals" / "datasets" / "full.jsonl"

sys.path.insert(0, str(REPO / "evals"))
import degradation as D  # noqa: E402


@pytest.fixture(scope="module")
def bf() -> Any:
    spec = importlib.util.spec_from_file_location("build_full_curve", BUILDER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def curve_cases() -> list[dict[str, Any]]:
    rows = [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("//")]
    return [r for r in rows if D.CURVE_TAG in r["tags"]]


# ---------------------------------------------------------------------------
# 1. Ailə dizaynı
# ---------------------------------------------------------------------------
def test_every_family_covers_every_turn_count(bf, curve_cases):
    by_family: dict[str, set[int]] = {}
    for row in curve_cases:
        fam = next(t[len("curve-"):] for t in row["tags"] if t.startswith("curve-"))
        n = next(int(t[len("turns-"):]) for t in row["tags"] if t.startswith("turns-"))
        by_family.setdefault(fam, set()).add(n)
    assert len(by_family) == len(bf.CURVE_FAMILIES)
    for fam, counts in by_family.items():
        assert counts == set(bf.CURVE_TURNS), (fam, counts)


def test_only_the_distance_changes_inside_a_family(bf, curve_cases):
    """Sual, iynə və faktlar SÖZBƏSÖZ eyni; yalnız aradakı növbələr fərqlidir."""
    families: dict[str, list[dict[str, Any]]] = {}
    for row in curve_cases:
        fam = next(t[len("curve-"):] for t in row["tags"] if t.startswith("curve-"))
        families.setdefault(fam, []).append(row)

    for fam, rows in families.items():
        questions = {r["input"][-1]["content"] for r in rows if len(r["input"]) > 1}
        assert len(questions) == 1, f"{fam}: sual variantlar arasında dəyişib"
        graders = {r["grader"] for r in rows}
        expects = {json.dumps(r["expect"], sort_keys=True) for r in rows}
        severities = {r["severity"] for r in rows}
        assert len(graders) == 1 and len(expects) == 1 and len(severities) == 1, fam
        # turns-1 variantı hər şeyi bir mesaja yığır — və o mesaj eyni sualı
        # SONDA saxlayır (faktlar + sual), yəni məzmun eynidir.
        single = [r for r in rows if len(r["input"]) == 1]
        assert len(single) == 1
        assert single[0]["input"][0]["content"].endswith(questions.pop())


def test_facts_are_always_in_the_first_message(bf, curve_cases):
    for family, facts, question, *_ in bf.CURVE_FAMILIES:
        rows = [r for r in curve_cases if f"curve-{family}" in r["tags"]]
        multi = [r for r in rows if len(r["input"]) > 1]
        firsts = {r["input"][0]["content"] for r in multi}
        assert firsts == {" ".join(facts)}, family


def test_fillers_carry_no_information(bf, curve_cases):
    """Doldurucuda sifariş nömrəsi, rəqəm və ya siyasət sözü OLMAMALIDIR."""
    banned = ("ORD-", "AZN", "day", "window", "warranty", "member", "promotion",
              "return", "delivered")
    for filler in bf.CURVE_FILLERS:
        low = filler.lower()
        for word in banned:
            assert word.lower() not in low, (filler, word)
        assert not any(ch.isdigit() for ch in filler), filler


def test_turn_counts_are_strictly_increasing_and_have_enough_fillers(bf):
    assert list(bf.CURVE_TURNS) == sorted(set(bf.CURVE_TURNS))
    assert len(bf.CURVE_FILLERS) >= max(bf.CURVE_TURNS) - 2
    with pytest.raises(ValueError):
        bf.curve_turns(["f"], "q?", max(bf.CURVE_TURNS) + 5)


def test_message_count_matches_the_turn_tag(curve_cases):
    for row in curve_cases:
        n = next(int(t[len("turns-"):]) for t in row["tags"] if t.startswith("turns-"))
        assert len(row["input"]) == n, row["id"]
        assert all(m["role"] == "user" for m in row["input"])


# ---------------------------------------------------------------------------
# 2. Assertion keyfiyyəti (A-01…A-26)
# ---------------------------------------------------------------------------
def test_assertions_reuse_audited_macros_and_have_no_bare_number(bf, curve_cases):
    audited = set(bf.MACROS.values()) | {v[1]["pattern"] for v in bf.LABEL_ASSERT.values()}
    for row in curve_cases:
        assert row["grader"] == "regex_match", row["id"]
        pattern = row["expect"]["pattern"]
        assert pattern in audited, (
            f"{row['id']}: iynə auditdən keçmiş makro deyil — yenidən icad "
            f"edilmiş pattern A-01 sinfi boşluq gətirir")


def test_every_case_is_traceable(curve_cases):
    for row in curve_cases:
        assert "FAILURE-TAXONOMY.md#C1 failure-onset" in row["source"], row["id"]
        assert "TRAPS.md#" in row["source"], row["id"]


def test_reject_pattern_covers_the_a27_phrasings(bf):
    """AP-017 canlı qaçışında tapılmış üç ifadə — hər üçü REAL cavabdandır."""
    import re
    real_answers = [
        "So — that window has already closed and a standard return would not be "
        "accepted.",
        "So actually you are not within the standard return window.",
        "Since the item isn't damaged, a standard return would not be accepted.",
    ]
    for text in real_answers:
        assert re.search(bf.REJECT, text, re.I), text
    # ƏKS İSTİQAMƏT: düzgün QƏBUL cavabı hələ də TUTULMAMALIDIR (A-08).
    accepting = [
        "Yes — you are still within the standard 14-day return window, so we can "
        "accept the return.",
        "You are inside the window; day 13 of 14, so a return is fine.",
    ]
    for text in accepting:
        assert not re.search(bf.REJECT, text, re.I), text


# ---------------------------------------------------------------------------
# 3. Analizator
# ---------------------------------------------------------------------------
def _row(case_id: str, family: str, turns: int, *, passed: bool,
         skipped: bool = False, attempt: int = 1) -> dict[str, Any]:
    return {"case_id": case_id, "attempt": attempt,
            "tags": [D.CURVE_TAG, f"curve-{family}", f"turns-{turns}"],
            "grade": {"passed": passed, "score": 1.0 if passed else 0.0,
                      "skipped": skipped},
            "response": {"text": "", "turns": []}}


def _report(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    out = tmp_path / "run.json"
    out.write_text(json.dumps({"run_id": "test", "results": rows}), encoding="utf-8")
    return tmp_path


def test_onset_is_the_first_failing_turn_count(tmp_path):
    root = _report(tmp_path, [
        _row("a-t1", "fam", 1, passed=True),
        _row("a-t3", "fam", 3, passed=True),
        _row("a-t5", "fam", 5, passed=False),
        _row("a-t8", "fam", 8, passed=False),
    ])
    curve = D.load([root])
    assert curve.families["fam"].onset == 5
    assert curve.drop_vs_first()[8] == pytest.approx(1.0)


def test_a_family_that_never_fails_has_no_onset(tmp_path):
    root = _report(tmp_path, [_row(f"a-t{n}", "fam", n, passed=True)
                              for n in (1, 3, 5, 8)])
    curve = D.load([root])
    assert curve.families["fam"].onset is None
    assert curve.families["fam"].measured


def test_infrastructure_error_is_not_reported_as_a_pass(tmp_path):
    """ÖLÇÜLMƏMİŞ ≠ SINMAMIŞ. Bu fərq itsə hesabat yalançı yaşıl olur."""
    root = _report(tmp_path, [_row(f"a-t{n}", "fam", n, passed=False, skipped=True)
                              for n in (1, 3, 5, 8)])
    curve = D.load([root])
    fam = curve.families["fam"]
    assert not fam.measured and fam.onset is None
    text = D.render(curve)
    assert "ölçülmədi" in text and "ÖLÇÜLMƏDİ" in text
    # Cədvəl sətrində «sınmadı» YAZILMAMALIDIR (izah mətnindəki «Bu, sınmadı
    # DEYİL» cümləsi istisnadır — o, məhz bu qarışıqlığın qarşısını alır).
    table = [l for l in text.splitlines() if l.startswith("fam")]
    assert table and all("sınmadı" not in l for l in table), table


def test_render_and_payload_survive_a_partial_curve(tmp_path):
    root = _report(tmp_path, [_row("a-t1", "fam", 1, passed=True),
                              _row("a-t8", "fam", 8, passed=False)])
    curve = D.load([root])
    assert curve.turn_counts == [1, 8]
    assert "t8" in D.render(curve)
    payload = D.to_payload(curve)
    assert payload["families"]["fam"]["onset"] == 8
    assert payload["aggregate"]["1"]["pass_rate"] == 1.0

"""`target/corpus/conflicts.py` — ziddiyyət və bayat bənd namizədləri.

DÖRD ŞEY QORUNUR (AP-035):

1. **Sərhəd.** Alət həqiqət təyin etmir: çıxış `conflict_candidates:`
   açarındadır, `stale_guess` TƏXMİNDİR və dəlili yanındadır, çıxış
   `CANONICAL.yaml` adlı fayla yazıla bilmir.
2. **İzlənəbilirlik.** Hər namizədin HƏR İKİ tərəfi üçün sənəddəki tam cümlə
   var və həmin cümlə doğrudan mənbə faylındadır.
3. **Ölçülmüş recall və yalançı müsbət.** Aurora rəqəmləri testdə
   sabitlənib və `target/corpus/CONFLICTS.md`-dəki rəqəmlərlə eynidir.
4. **Zəncir yoxlaması boş deyil.** Aurora-nın versiya zənciri bütövdür, ona
   görə hər qırıq növü SÜNİ mutasiya ilə yoxlanılır — yoxsa "0 problem"
   nəticəsi alətin işlədiyini deyil, heç nəyə baxmadığını göstərərdi.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from target.corpus import conflicts as C
from target.corpus import extract as E

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "target" / "corpus"
CONFLICTS_MD = CORPUS / "CONFLICTS.md"

#: `python target/corpus/conflicts.py score` ilə ölçülüb (AP-035).
MEASURED = {
    "stale_total": 25,          # `parameters[].supersedes` — rəqəmlə ifadə olunan
    "stale_found": 20,
    "guess_correct": 20,
    "guess_wrong": 0,
    "collision_total": 5,
    "collision_found": 5,
    "emitted_pairs": 105,
    "false_positives": 8,
}


@pytest.fixture(scope="module")
def aurora():
    canonical = yaml.safe_load((CORPUS / "CANONICAL.yaml").read_text(encoding="utf-8"))
    paths = [CORPUS / d["file"] for d in canonical["meta"]["documents"]]
    rep = C.analyse(paths)
    return canonical, rep, C.score(canonical, rep)


# ---------------------------------------------------------------------------
# 1. Sərhəd — namizəd, həqiqət deyil
# ---------------------------------------------------------------------------
def test_output_key_is_candidates_not_truth(aurora):
    _, rep, _ = aurora
    payload = rep.to_payload()
    assert "conflict_candidates" in payload
    assert "parameters" not in payload and "colliding_values" not in payload
    assert payload["meta"]["status"].startswith("DRAFT")


def test_cannot_write_over_canonical(aurora, tmp_path):
    _, rep, _ = aurora
    with pytest.raises(ValueError):
        C.write_draft(rep, tmp_path / "CANONICAL.yaml")
    out = C.write_draft(rep, tmp_path / "conflicts.draft.yaml")
    loaded = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert set(loaded["conflict_candidates"]) == {
        "same_concept_different_value", "same_number_different_concept", "version_chain"}


def test_stale_guess_is_a_guess_with_evidence(aurora):
    """Təxminin YANINDA dəlil olmalıdır — auditor onu yoxlaya bilsin."""
    _, rep, _ = aurora
    for c in rep.value_conflicts:
        assert c.stale_guess in {"a", "b", "unknown"}
        assert c.stale_confidence in {"high", "low", "none"}
        assert len(c.stale_evidence) == 2, c.stale_evidence
        assert c.a["candidate_id"] != c.b["candidate_id"]


# ---------------------------------------------------------------------------
# 2. İzlənəbilirlik — hər iki iqtibas mənbədədir
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    return " ".join(s.replace("**", "").replace("*", "").split())


def test_both_quotes_are_really_in_the_source_documents(aurora):
    _, rep, _ = aurora
    texts = {p.name: _norm(p.read_text(encoding="utf-8")) for p in E.DEFAULT_DOCS}
    for c in rep.value_conflicts[:60]:
        for side in (c.a, c.b):
            assert _norm(side["quote"]) in texts[side["doc"]], side
    for g in rep.collisions:
        for m in g["meanings"] if isinstance(g, dict) else g.meanings:
            assert _norm(m["quote"]) in texts[m["doc"]], m


# ---------------------------------------------------------------------------
# 3. Ölçülmüş rəqəmlər
# ---------------------------------------------------------------------------
def test_stale_pair_recall_is_measured(aurora):
    _, _, sb = aurora
    assert sb.stale_total == MEASURED["stale_total"]
    assert sb.stale_found == MEASURED["stale_found"]
    assert sb.stale_recall == pytest.approx(0.80, abs=0.01)


def test_stale_side_guess_never_points_at_the_live_value(aurora):
    """Ən təhlükəli səhv: alət CANLI dəyəri 'bayat' işarələsin."""
    _, _, sb = aurora
    assert sb.stale_guess_wrong == MEASURED["guess_wrong"]
    assert sb.stale_guess_correct == MEASURED["guess_correct"]


def test_missed_pairs_are_extraction_gaps_not_detection_gaps(aurora):
    """Tapılmayan 5 cütün hər ikisi/biri NAMİZƏDLƏRDƏ ÜMUMİYYƏTLƏ YOXDUR.

    Yəni tavan `extract.py`-dədir (AP-034-ün sənədləşmiş boşluqları), ziddiyyət
    məntiqində deyil: çıxarıla bilən 20 cütün 20-si tapılır.
    """
    canonical, rep, sb = aurora
    cands = [c for p in E.DEFAULT_DOCS for c in E.extract_document(p)]
    present = {(c.doc, E._norm_value(c.value), c.unit) for c in cands}
    params = {p["id"]: p for p in canonical["parameters"]}
    for missed in sb.stale_missed:
        pid = missed.split(" ")[0]
        p = params[pid]
        sup = p["supersedes"]
        au = E.UNIT_MAP.get(str(p["unit"]))
        su = E.UNIT_MAP.get(str(sup.get("unit", p["unit"])))
        both = ((p["doc"], E._norm_value(p["value"]), au) in present
                and (p["doc"], E._norm_value(sup["value"]), su) in present)
        assert not both, f"{pid}: hər iki dəyər namizəddədir, deməli aşkarlama boşluğudur"


def test_collision_recall_covers_every_documented_group(aurora):
    _, _, sb = aurora
    assert sb.collision_total == MEASURED["collision_total"]
    assert sb.collision_found == MEASURED["collision_found"]
    assert sb.collision_missed == []


def test_false_positive_rate_is_bounded(aurora):
    """Yalançı müsbət = eyni parametrin iki üzünü ziddiyyət sanmaq."""
    _, _, sb = aurora
    assert sb.emitted_pairs == MEASURED["emitted_pairs"]
    assert sb.pair_false_positive == MEASURED["false_positives"]
    assert sb.pair_fp_rate < 0.10


def test_found_pairs_rank_inside_the_first_screen(aurora):
    """Sıralama işləməlidir: 105 namizədin hamısını oxumaq auditin qazancını yeyir."""
    _, _, sb = aurora
    assert max(sb.stale_ranks) <= 50, sb.stale_ranks


def test_same_number_is_not_reported_as_a_contradiction(aurora):
    """A-07: 30 gün həm bayat standart, həm canlı Plus pəncərəsidir — TOQQUŞMA,
    ziddiyyət deyil. Hesabat 1 eyni dəyərli cüt verməməlidir."""
    _, rep, _ = aurora
    for c in rep.value_conflicts:
        same = (C._comparable_value(c.a["value"], c.a["unit"])
                == C._comparable_value(c.b["value"], c.b["unit"]))
        assert not (same and c.a["unit"] == c.b["unit"]), c


# ---------------------------------------------------------------------------
# 4. Versiya zənciri — mutasiya ilə yoxlanılır
# ---------------------------------------------------------------------------
AURORA_CHAIN_CODES = {"superseded_cue_outside_appendix"}


def test_aurora_chain_is_intact(aurora):
    _, rep, _ = aurora
    codes = {i.code for i in rep.chain_issues}
    assert codes <= AURORA_CHAIN_CODES, codes


@pytest.mark.parametrize("mutation,expected", [
    (("> **Supersedes:** v3.2 (in force 2024-03-01 through 2025-12-31)",
      "> **Supersedes:** v3.1 (in force 2024-03-01 through 2025-12-31)"),
     "appendix_version_mismatch"),
    (("> **Supersedes:** v3.2 (in force 2024-03-01 through 2025-12-31)",
      "> **Supersedes:** v3.2 (in force 2024-03-01 through 2025-11-30)"),
     "supersedes_window_gap"),
    (("## Appendix A — Superseded provisions (v3.2)",
      "## Appendix A — Superseded provisions"),
     "appendix_version_unstamped"),
    (("**A.1 Return window (superseded 2026-01-01).**",
      "**A.1 Return window (superseded 2026-02-15).**"),
     "clause_superseded_date_mismatch"),
    (("Under v3.2 the standard return window was", "Under v2.9 the standard return window was"),
     "clause_version_unknown"),
])
def test_chain_break_is_detected(tmp_path, mutation, expected):
    """Aurora zənciri bütöv olduğu üçün hər qırıq növü SÜNİ yaradılır."""
    src = (CORPUS / "returns-and-refunds.md").read_text(encoding="utf-8")
    old, new = mutation
    assert old in src, old
    doc = tmp_path / "returns-and-refunds.md"
    doc.write_text(src.replace(old, new), encoding="utf-8")
    codes = {i.code for i in C.version_chain([doc])}
    assert expected in codes, codes


def test_chain_reports_nothing_for_a_clean_mutation_free_copy(tmp_path):
    src = (CORPUS / "returns-and-refunds.md").read_text(encoding="utf-8")
    doc = tmp_path / "returns-and-refunds.md"
    doc.write_text(src, encoding="utf-8")
    assert [i.code for i in C.version_chain([doc])] == []


# ---------------------------------------------------------------------------
# 5. Sənəd rəqəmlərlə eynidir
# ---------------------------------------------------------------------------
def test_documented_numbers_match_the_measurement(aurora):
    _, _, sb = aurora
    doc = CONFLICTS_MD.read_text(encoding="utf-8")
    for needle in (f"{sb.stale_found}/{sb.stale_total}",
                   f"{sb.collision_found}/{sb.collision_total}",
                   f"{sb.pair_false_positive}", f"{sb.emitted_pairs}"):
        assert needle in doc, f"CONFLICTS.md-də yoxdur: {needle}"


def test_conflicts_doc_states_the_boundary():
    doc = CONFLICTS_MD.read_text(encoding="utf-8")
    assert "namizəd" in doc.lower()
    assert "həqiqət təyin etmir" in doc or "qərar vermir" in doc

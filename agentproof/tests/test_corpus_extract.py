"""`target/corpus/extract.py` — siyasət sənədindən parametr namizədləri.

ÜÇ ŞEY QORUNUR (AP-034):

1. **Sərhəd.** Alət ground truth qurmur. Çıxış `parameter_candidates:`
   açarındadır, `status`/`doc_version`/`applies_when` boş gəlir, çıxış
   CANONICAL.yaml adlı fayla yazıla bilmir və sxem validatoru həmin qaralamanı
   həqiqət cədvəli kimi qəbul etmir.
2. **İzlənəbilirlik.** Hər namizədin yanında sənəddəki TAM cümlə var və həmin
   cümlə doğrudan da mənbə faylındadır — auditor yoxlaya bilsin.
3. **Ölçülmüş recall.** Aurora üzərindəki rəqəm testdə sabitlənib və
   `target/corpus/EXTRACTION.md`-də yazılan rəqəmlə eynidir — "avtomatik
   çıxarır" iddiası ölçülmüş rəqəm olmadan sənədə düşməsin.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from target.corpus import extract as E
from target.corpus import schema as S

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "target" / "corpus"
EXTRACTION_MD = CORPUS / "EXTRACTION.md"

#: `python target/corpus/extract.py score` ilə ölçülüb (AP-034).
MEASURED = {
    "parameters": 96,
    "found": 85,
    "candidates": 158,
    "useful": 137,
    "misses": 11,
}


@pytest.fixture(scope="module")
def aurora_run():
    canonical = yaml.safe_load((CORPUS / "CANONICAL.yaml").read_text(encoding="utf-8"))
    files = sorted(d["file"] for d in canonical["meta"]["documents"])
    paths = [CORPUS / f for f in files]
    cands, docs, texts, clause_texts = E._load_docs(paths)
    return canonical, cands, docs, E.score(canonical, cands, texts, clause_texts)


# ============================================================ sənəd parsinqi
SYNTHETIC = """\
# Loan Policy

> **Document ID:** NL-LOAN
> **Version:** 2.0
> **Effective from:** 2026-01-01

## 2. Loan period

2.1 The standard loan period is **21 calendar days**.

2.2 Business days are Monday to Friday. Parcels above **20.0 kg** are refused.

2.3 The desk closes at **17:30** (UTC+04:00) on weekdays.

| Days elapsed | Overdue? |
|---|---|
| 21 | No |
| 22 | Yes |

## Appendix A — Superseded provisions (v1.4)

**A.1 Loan period (superseded 2026-01-01).** Under v1.4 the loan period was **14 days**.
"""


@pytest.fixture()
def synthetic(tmp_path) -> Path:
    p = tmp_path / "loans.md"
    p.write_text(SYNTHETIC, encoding="utf-8")
    return p


def test_front_matter_is_parsed(synthetic):
    doc = E.parse_document(synthetic)
    assert (doc.doc_id, doc.version, doc.effective_from) == ("NL-LOAN", "2.0", "2026-01-01")


def test_clauses_use_the_anchor_layer_keys(synthetic):
    keys = [c.key for c in E.parse_document(synthetic).clauses]
    assert "2.1" in keys and "2.2" in keys and "appendix-a.1" in keys


def test_appendix_clause_is_flagged(synthetic):
    clause = next(c for c in E.parse_document(synthetic).clauses if c.key == "appendix-a.1")
    assert clause.appendix and clause.label == "Appendix A.1"


def test_clause_parser_shares_regexes_with_the_anchor_layer():
    """İki ayrı bənd parseri namizədi başqa bəndə yazardı.

    Modul obyekti də EYNİ olmalıdır: `import anchors` ilə `target.corpus.anchors`
    iki ayrı modul yaradır və vəziyyət ikiləşir.
    """
    from target.corpus import anchors as A

    assert E.A is A, "anchors modulu iki dəfə yüklənib"
    assert E.A.CLAUSE_RE is A._CLAUSE_RE
    assert E.A.APPENDIX_CLAUSE_RE is A._APPENDIX_CLAUSE_RE


# ============================================================ cümləyə bölmə
def test_decimal_and_version_dots_do_not_split_sentences():
    clause = E.Clause("4.3", "§4.3", "4. Costs", [
        "4.3 Items above 20.0 kg are refused. Under v3.2 the fee was 45.00 AZN."], False)
    assert list(E.iter_sentences(clause)) == [
        "Items above 20.0 kg are refused.",
        "Under v3.2 the fee was 45.00 AZN.",
    ]


def test_leading_clause_number_is_not_read_as_a_quantity(synthetic):
    """`2.2 Business days are ...` → `2.2 business_day` UYDURMA namizəddir."""
    cands = E.extract_document(synthetic)
    assert not [c for c in cands if str(c.value) == "2.2"], \
        "bənd nömrəsi kəmiyyət kimi oxunub"


def test_utc_offset_is_not_a_time_of_day(synthetic):
    times = {str(c.value) for c in E.extract_document(synthetic) if c.unit == "time_of_day"}
    assert times == {"17:30"}, f"`UTC+04:00` saat kimi tutulub: {times}"


def test_table_rows_are_separate_units():
    clause = E.Clause("2", "§2", "2. X", ["| 21 | No |", "| 22 | Yes |"], False)
    assert list(E.iter_sentences(clause)) == ["| 21 | No |", "| 22 | Yes |"]


# ============================================================ vahid qatı
def test_range_becomes_an_interval_value():
    assert ("4|7", "business_day") in E.sentence_quantities(
        "Delivery takes 4–7 business days.")


def test_weight_and_clock_units_are_extracted():
    got = dict(E.sentence_quantities("Parcels above 20.0 kg are refused after 14:00."))
    assert got["20"] == "kg" and got["14:00"] == "time_of_day"


def test_bare_numbers_are_not_candidates():
    """Vahidsiz rəqəm parametr deyil — onları saxlamaq namizəd sayını şişirdir."""
    assert E.sentence_quantities("See section 5 and the day 0 rule.") == []


def test_multilingual_engine_is_reused():
    """Motor `graders/canonical.py`-dir — çoxdilli dəstək oradan gəlir."""
    assert ("30", "day") in E.sentence_quantities("Qaytarma müddəti 30 gündür.")


# ============================================================ sərhəd: qərar insanındır
def test_human_fields_are_left_empty(aurora_run):
    _, cands, _, _ = aurora_run
    filled = [c.candidate_id for c in cands
              if c.status or c.doc_version or c.applies_when]
    assert not filled, f"alət insanın sahəsini doldurub: {filled[:5]}"


def test_draft_refuses_to_write_to_canonical_yaml(tmp_path, synthetic):
    cands = E.extract_document(synthetic)
    with pytest.raises(ValueError, match="CANONICAL.yaml"):
        E.write_draft(cands, [E.parse_document(synthetic)], tmp_path / "CANONICAL.yaml")


def test_draft_is_not_a_canonical_table(tmp_path, synthetic):
    out = E.write_draft(E.extract_document(synthetic),
                        [E.parse_document(synthetic)], tmp_path / "draft.yaml")
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert "parameters" not in doc and "parameter_candidates" in doc
    assert not S.validate(doc).ok, \
        "qaralama sxemdən keçir — insan təsdiqi olmadan həqiqət cədvəli kimi işlənə bilər"


def test_draft_header_states_it_is_not_ground_truth(tmp_path, synthetic):
    out = E.write_draft(E.extract_document(synthetic),
                        [E.parse_document(synthetic)], tmp_path / "draft.yaml")
    assert "GROUND TRUTH DEYİL" in out.read_text(encoding="utf-8")


def test_appendix_candidates_are_flagged_as_likely_superseded(synthetic):
    stale = [c for c in E.extract_document(synthetic) if c.section == "Appendix A.1"]
    assert stale and all(c.source["likely_superseded"] for c in stale)


# ============================================================ izlənəbilirlik
def test_every_candidate_carries_a_verifiable_quote(aurora_run):
    """İqtibas mənbə faylında HƏQİQƏTƏN var — auditor yoxlaya bilsin."""
    _, cands, _, _ = aurora_run
    texts = {p.name: re.sub(r"\s+", " ", p.read_text(encoding="utf-8").replace("**", ""))
             for p in CORPUS.glob("*.md")}
    missing = [c.candidate_id for c in cands
               if not c.source["quote"] or c.source["quote"] not in texts[c.doc]]
    assert not missing, f"mənbədə tapılmayan iqtibas: {missing[:5]}"


def test_every_candidate_names_a_document_and_a_clause(aurora_run):
    _, cands, _, _ = aurora_run
    bad = [c.candidate_id for c in cands
           if not c.doc.endswith(".md") or not c.section]
    assert not bad


# ============================================================ ölçülmüş recall
def test_measured_recall_on_aurora(aurora_run):
    _, _, _, rep = aurora_run
    assert rep.total == MEASURED["parameters"]
    assert rep.found == MEASURED["found"], (
        f"recall dəyişib: {rep.found}/{rep.total}. Rəqəm dəyişdisə "
        f"target/corpus/EXTRACTION.md və MEASURED yenilənməlidir — "
        f"ölçülməmiş iddia sənədə düşməməlidir."
    )
    assert rep.candidates == MEASURED["candidates"]
    assert rep.useful == MEASURED["useful"]
    assert len(rep.misses) == MEASURED["misses"]


def test_miss_taxonomy_is_complete_and_classified(aurora_run):
    """Hər tapılmayanın SƏBƏBİ var — 'unclassified' yol xəritəsi deyil."""
    _, _, _, rep = aurora_run
    reasons = {m.reason for m in rep.misses}
    assert "unclassified" not in reasons and "clause_not_parsed" not in reasons, reasons
    assert reasons == {
        "zero_expressed_in_words", "non_numeric", "qualifier_between_number_and_unit",
        "unit_synonym_missing", "hyphenated_compound_modifier",
        "enumerated_list_value", "number_as_word",
    }


def test_documented_numbers_match_the_measurement(aurora_run):
    """`EXTRACTION.md`-dəki rəqəmlər ölçülən rəqəmlərdir, iddia deyil."""
    _, _, _, rep = aurora_run
    doc = EXTRACTION_MD.read_text(encoding="utf-8")
    for needle in (f"{rep.found}/{rep.total}", f"{rep.recall_doc:.1%}",
                   f"{rep.useful}/{rep.candidates}", f"{rep.useful_rate:.1%}"):
        assert needle in doc, f"EXTRACTION.md-də yoxdur: {needle}"


def test_extraction_doc_states_the_limit_of_the_claim():
    doc = EXTRACTION_MD.read_text(encoding="utf-8")
    assert "ground truth qurmur" in doc.lower() or "ground truth qurmur" in doc
    assert "Markdown" in doc, "giriş formatının məhdudiyyəti yazılmayıb"

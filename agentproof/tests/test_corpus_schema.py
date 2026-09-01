"""`target/corpus/schema.py` — CANONICAL sxeminin korpusdan asılı olmayan testləri.

İKİ ŞEY QORUNUR (AP-033):

1. **Reqressiya yoxdur.** `verify_fixtures.py`-nin tarixi 1338 assertion-u
   sxem qatına köçürüldükdən sonra da tam olaraq 1338 qalır. Say azalarsa
   korpus səssizcə daha az yoxlanır — testin əsas məqsədi budur.
2. **Sxem korpusdan asılı deyil.** Validator heç bir Aurora adı bilmir:
   tamam başqa domendə (kitabxana qaydaları) qurulmuş süni korpus da
   təmiz keçir, pozulmuş korpus isə DƏQIQ kodlarla sınır.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from target.corpus import schema as S

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "target" / "corpus"
CANONICAL = CORPUS / "CANONICAL.yaml"

#: `verify_fixtures.py`-nin AP-033-dən əvvəlki assertion sayı.
LEGACY_TOTAL = 1338
#: Onun sxem qatına düşən hissəsi (96 parametr × 7 sahə + 36 sərhəd × 3 + 27 tələ).
LEGACY_SCHEMA_SHARE = 807


@pytest.fixture(scope="module")
def aurora() -> dict:
    return yaml.safe_load(CANONICAL.read_text(encoding="utf-8"))


# ------------------------------------------------------------ referans korpus
def test_aurora_corpus_passes_schema(aurora):
    rep = S.validate(aurora)
    assert rep.ok, "referans korpus öz sxemindən keçmir:\n  " + "\n  ".join(
        str(f) for f in rep.errors
    )


def test_aurora_has_exactly_one_known_warning(aurora):
    """Bilinən sapma: RC-12 parametr cədvəlində olmayan qaydaya baxır.

    Xəbərdarlıq gizlədilmir — `docs/CANONICAL-SCHEMA.md` §"Bilinən sapmalar"
    onu adı ilə yazır. Sayı artarsa korpusda yeni asılı istinad yaranıb.
    """
    warns = S.validate(aurora).warnings
    assert [w.code for w in warns] == ["resolved.deciding_parameter_known"], (
        "gözlənilməyən xəbərdarlıq(lar): " + "; ".join(str(w) for w in warns)
    )


# ------------------------------------------------------------ reqressiya bəndi
def test_legacy_schema_assertion_count_is_preserved(aurora):
    rep = S.validate(aurora)
    assert rep.legacy_checks == LEGACY_SCHEMA_SHARE, (
        f"sxem qatındakı tarixi assertion sayı {rep.legacy_checks}, "
        f"gözlənilən {LEGACY_SCHEMA_SHARE} — korpus səssizcə daha az yoxlanır"
    )
    assert rep.checks > rep.legacy_checks, "yeni sxem qaydaları itib"


def test_verify_fixtures_still_reports_the_full_legacy_count():
    """`verify_fixtures.py` exit 0 verir və 1338 tarixi assertion sağdır."""
    proc = subprocess.run(
        [sys.executable, str(CORPUS / "verify_fixtures.py")],
        capture_output=True, text=True, cwd=str(REPO),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    line = next(l for l in proc.stdout.splitlines() if l.startswith("legacy assertions"))
    reported = int(line.split(":")[1].strip().split()[0])
    assert reported == LEGACY_TOTAL, f"{line!r} — tarixi assertion sayı azalıb"


# ------------------------------------------------------------------ JSON Schema
def test_emitted_json_schema_file_is_in_sync():
    on_disk = json.loads(S.DEFAULT_JSON_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert on_disk == S.json_schema(), (
        "canonical.schema.json köhnəlib — `python target/corpus/schema.py "
        "emit-json-schema` qaçır"
    )


def test_aurora_validates_against_the_emitted_json_schema(aurora):
    from jsonschema import Draft202012Validator

    doc = json.loads(json.dumps(aurora, default=str))  # date → str
    errs = list(Draft202012Validator(S.json_schema()).iter_errors(doc))
    assert not errs, "\n".join(f"{list(e.path)}: {e.message}" for e in errs[:10])


def test_json_schema_covers_every_required_section():
    js = S.json_schema()
    assert set(js["required"]) == set(S.REQUIRED_SECTIONS)
    for name in S.REQUIRED_SECTIONS + S.OPTIONAL_SECTIONS:
        assert name in js["properties"], f"JSON Schema-da bölmə yoxdur: {name}"


# ------------------------------------------------ korpusdan asılı olmama sübutu
def _library_corpus() -> dict:
    """Aurora ilə heç bir ortaq adı olmayan minimal korpus (kitabxana qaydaları)."""
    return {
        "meta": {
            "company": "Nizami Library",
            "corpus_version": "0.1",
            "currency": "EUR",
            "evaluation_reference_date": "2026-09-01",
            "documents": [
                {"file": "loans.md", "id": "NL-LOAN", "version": "2.0",
                 "effective_from": "2026-01-01"},
            ],
        },
        "precedence_ladder": [
            {"rank": 1, "rule": "reference_only", "source": "loans.md §1"},
            {"rank": 2, "rule": "standard_loan", "source": "loans.md §2"},
        ],
        "counting_rules": {"loan_period": {"anchor": "checkout_date",
                                           "calendar_or_business": "calendar"}},
        "parameters": [
            {"id": "loan_period_days", "value": 21, "unit": "days", "status": "active",
             "doc": "loans.md", "section": "§2.1", "doc_version": "2.0",
             "applies_when": "adult member; general collection",
             "precedence_rank": 2,
             "supersedes": {"value": 14, "doc_version": "1.4",
                            "effective_until": "2025-12-31"},
             "boundary": {"dimension": "days_since_checkout", "points": [
                 {"value": 20, "expected": "on_time"},
                 {"value": 21, "expected": "on_time"},
                 {"value": 22, "expected": "overdue"},
             ]}},
            {"id": "late_fee_per_day", "value": 0.20, "unit": "EUR", "status": "active",
             "doc": "loans.md", "section": "§3.1", "doc_version": "2.0",
             "applies_when": "loan overdue; general collection"},
        ],
        "superseded_index": [
            {"parameter": "loan_period_days", "stale_value": 14, "doc": "loans.md",
             "appendix": "Appendix A.1", "not_true_from": "2026-01-01"},
        ],
        "resolved_loan_periods": [
            {"id": "LC-01", "deciding_parameter": "loan_period_days", "deciding_rank": 2},
        ],
        "gaps": [
            {"id": "GAP-01", "topic": "Inter-library loan fees",
             "question_examples": ["What does an inter-library loan cost?"],
             "correct_behaviour": ["state_information_not_available"]},
        ],
    }


def test_validator_accepts_a_completely_different_corpus():
    rep = S.validate(_library_corpus())
    assert rep.ok, "sxem Aurora-ya bağlı qalıb:\n  " + "\n  ".join(str(f) for f in rep.errors)
    assert not rep.warnings, "\n".join(str(w) for w in rep.warnings)


# ------------------------------------------------------------- mənfi hallar
def _codes(doc: dict) -> set[str]:
    return {f.code for f in S.validate(doc).errors}


def test_missing_required_section_is_reported():
    doc = _library_corpus()
    del doc["counting_rules"]
    assert "root.required_section" in _codes(doc)


def test_missing_required_parameter_field_is_reported():
    doc = _library_corpus()
    del doc["parameters"][0]["applies_when"]
    rep = S.validate(doc)
    assert any(f.code == "parameter.required_field" and "applies_when" in f.message
               for f in rep.errors)


def test_boundary_with_two_points_is_reported():
    doc = _library_corpus()
    doc["parameters"][0]["boundary"]["points"] = [
        {"value": 20, "expected": "on_time"}, {"value": 22, "expected": "overdue"}]
    assert "boundary.min_points" in _codes(doc)


def test_boundary_out_of_order_is_reported():
    doc = _library_corpus()
    doc["parameters"][0]["boundary"]["points"].reverse()
    assert "boundary.ascending" in _codes(doc)


def test_boundary_with_one_outcome_is_not_a_boundary():
    doc = _library_corpus()
    for pt in doc["parameters"][0]["boundary"]["points"]:
        pt["expected"] = "on_time"
    assert "boundary.distinct_expected" in _codes(doc)


def test_superseded_index_pointing_at_an_unknown_parameter_is_reported():
    doc = _library_corpus()
    doc["superseded_index"][0]["parameter"] = "no_such_parameter"
    assert "superseded_index.parameter_known" in _codes(doc)


def test_superseded_index_without_a_supersedes_block_is_reported():
    """Tələ indeksdədir, amma parametrdə köhnə dəyər yoxdur → tələ ölçülməzdir."""
    doc = _library_corpus()
    del doc["parameters"][0]["supersedes"]
    assert "superseded_index.parameter_has_supersedes" in _codes(doc)


def test_supersedes_repeating_the_active_value_is_not_a_trap():
    doc = _library_corpus()
    doc["parameters"][0]["supersedes"]["value"] = 21
    assert "supersedes.value_differs" in _codes(doc)


def test_null_supersedes_value_requires_a_note():
    doc = _library_corpus()
    doc["parameters"][0]["supersedes"]["value"] = None
    assert "supersedes.null_value_needs_note" in _codes(doc)
    doc["parameters"][0]["supersedes"]["note"] = "no limit existed under v1.4"
    assert "supersedes.null_value_needs_note" not in _codes(doc)


def test_unregistered_document_is_reported():
    doc = _library_corpus()
    doc["parameters"][0]["doc"] = "not-in-registry.md"
    assert "parameter.doc_registered" in _codes(doc)


def test_stale_doc_version_on_a_parameter_is_reported():
    doc = _library_corpus()
    doc["parameters"][0]["doc_version"] = "1.4"
    assert "parameter.doc_version_matches" in _codes(doc)


def test_duplicate_parameter_id_is_reported():
    doc = _library_corpus()
    doc["parameters"].append(dict(doc["parameters"][1]))
    assert "parameter.duplicate_id" in _codes(doc)


def test_unknown_precedence_rank_is_reported():
    doc = _library_corpus()
    doc["parameters"][0]["precedence_rank"] = 9
    assert "parameter.precedence_rank_known" in _codes(doc)


def test_gap_in_the_precedence_ladder_is_reported():
    doc = _library_corpus()
    doc["precedence_ladder"][1]["rank"] = 4
    assert "ladder.rank_gap" in _codes(doc)


def test_bad_status_enum_is_reported():
    doc = _library_corpus()
    doc["parameters"][0]["status"] = "draft"
    assert "parameter.status_enum" in _codes(doc)


def test_currency_unit_must_match_meta_currency():
    doc = _library_corpus()
    doc["parameters"][1]["unit"] = "USD"
    assert "parameter.currency_matches_meta" in _codes(doc)


def test_value_must_be_scalar_or_interval():
    doc = _library_corpus()
    doc["parameters"][0]["value"] = {"min": 14, "max": 21}
    assert "parameter.value_type" in _codes(doc)
    doc["parameters"][0]["value"] = [14, 21]
    assert "parameter.value_type" not in _codes(doc)


def test_gap_without_question_examples_is_reported():
    doc = _library_corpus()
    del doc["gaps"][0]["question_examples"]
    assert "gap.required_field" in _codes(doc)


def test_non_mapping_root_is_reported():
    assert "root.not_a_mapping" in {f.code for f in S.validate(["nope"]).errors}


# ------------------------------------------------------------------ köməkçilər
@pytest.mark.parametrize("raw,expected", [
    ("§2.1", "2.1"),
    ("2.1", "2.1"),
    ("§4", "4"),
    ("Appendix A.3", "appendix-a.3"),
    ("Appendix A", "appendix-a"),
    ("preamble", None),
])
def test_section_key(raw, expected):
    assert S.section_key(raw) == expected


def test_cli_validate_returns_zero_for_the_reference_corpus():
    proc = subprocess.run(
        [sys.executable, str(CORPUS / "schema.py"), "validate", str(CANONICAL)],
        capture_output=True, text=True, cwd=str(REPO),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK — schema valid." in proc.stdout


# ---------------------------------------------------------------- sənəd sürüşməsi
def test_every_schema_field_is_documented():
    """Yeni sahə əlavə edən adam `docs/CANONICAL-SCHEMA.md`-ni də yeniləməlidir.

    Sənədləşdirilməmiş sxem AP-033-ün həll etdiyi problemin özüdür — sahə
    cədvəli yenidən yalnız Python-dan oxunan hala düşməsin.
    """
    doc = (REPO / "docs" / "CANONICAL-SCHEMA.md").read_text(encoding="utf-8")
    missing = [
        f"{section}.{name}"
        for section, specs in S.SECTION_SPECS.items()
        for name in specs
        if f"`{name}`" not in doc
    ]
    assert not missing, "sənəddə yazılmayan sahə(lər): " + ", ".join(missing)

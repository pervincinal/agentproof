"""AP-036 — generator Aurora-ya SABİT BAĞLI DEYİL.

Metodoloji iddia (`build_full.py` docstring, `COVERAGE.md §10`) budur: «test
halları siyasət sənədindən TÖRƏDİLİR, hazır dataset kimi qəbul edilmir».
İddia yalnız bir korpusda doğrudursa, o, iddia deyil — təsadüfdür.

BEŞ ŞEY QORUNUR:

1. Aurora dataseti BAYT-BAYTINA eynidir (refaktor heç nəyi dəyişməyib).
2. Sabit kod qalmayıb: referens tarixi `CANONICAL.meta`-dan gəlir, korpus
   yolu və çıxış yolu konfiqurasiyadan.
3. İkinci korpus (Nizami Public Library) üzərində generator KODA TOXUNMADAN
   keçərli jsonl verir.
4. Etiket adları korpusdan gəlir: iki korpusun etiket dəstləri KƏSİŞMİR.
5. Dürüstlük: hansı blokların həqiqətən TÖRƏDİLDİYİ, hansının Aurora
   məzmununa əl ilə yazıldığı konfiqurasiyada açıq yazılıb.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
BUILDER = REPO / "evals" / "datasets" / "build_full.py"
LIBRARY_CORPUS = REPO / "target" / "corpus-library"
LIBRARY_JSONL = REPO / "evals" / "datasets" / "library.jsonl"


@pytest.fixture(scope="module")
def bf() -> Any:
    spec = importlib.util.spec_from_file_location("build_full_second", BUILDER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# 1. Sabit kod qalmayıb
# ---------------------------------------------------------------------------
def test_no_hardcoded_reference_date_or_corpus_path():
    src = BUILDER.read_text(encoding="utf-8")
    assert "REF_DATE = " not in src, "referens tarixi yenidən sabit kodlanıb"
    assert 'CORPUS = ROOT / "target" / "corpus"' not in src, "korpus yolu sabit kodlanıb"
    # Kod içində Aurora sənəd adları qalmamalıdır — onlar konfiqurasiyadadır.
    # (Case MƏTNLƏRİ ayrı məsələdir: `r6`/`s`/`c1` blokları Aurora məzmunudur
    # və `blocks:` siyahısında açıq işarələnib.)
    assert "target/corpus/CANONICAL.yaml" not in src


def test_reference_date_comes_from_canonical(bf):
    aurora = bf.AURORA
    canonical = aurora.canonical()
    assert bf.CorpusConfig.ref_date(canonical) == "2026-09-01"
    canonical["meta"].pop("evaluation_reference_date")
    with pytest.raises(ValueError, match="evaluation_reference_date"):
        bf.CorpusConfig.ref_date(canonical)


def test_future_dates_in_a_question_are_rejected(bf):
    """Sabit tarix olsaydı bu qoruma mənasız olardı."""
    case = {"id": "x", "input": "My order was delivered on 2027-01-01.", "tags": []}
    with pytest.raises(ValueError, match="2027-01-01"):
        bf._assert_no_future_dates([case], "2026-09-01")
    # Gözlənilən CAVABDA gələcək tarix NORMALDIR (zəmanətin bitmə tarixi).
    ok = {"id": "y", "input": "When does it expire?",
          "expect": {"all": ["2027-03-01"]}, "tags": []}
    bf._assert_no_future_dates([ok], "2026-09-01")


# ---------------------------------------------------------------------------
# 2. Aurora dəyişməyib
# ---------------------------------------------------------------------------
def test_aurora_dataset_is_byte_identical():
    r = subprocess.run([sys.executable, str(BUILDER), "--check"],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "185 case" in r.stdout


# ---------------------------------------------------------------------------
# 3. İkinci korpus
# ---------------------------------------------------------------------------
def test_library_corpus_validates_against_the_shared_schema():
    from target.corpus import schema as S
    rep = S.validate_file(LIBRARY_CORPUS / "CANONICAL.yaml")
    assert rep.ok, [f.message for f in rep.findings if f.level == "ERROR"]


def test_library_dataset_is_in_sync_with_the_generator():
    r = subprocess.run([sys.executable, str(BUILDER), "--corpus", "library", "--check"],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr


def test_library_dataset_is_valid_and_traceable():
    rows = [json.loads(l) for l in LIBRARY_JSONL.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("//")]
    assert len(rows) == 24, len(rows)
    canonical = yaml.safe_load((LIBRARY_CORPUS / "CANONICAL.yaml").read_text(encoding="utf-8"))
    param_ids = {p["id"] for p in canonical["parameters"]}
    ids = set()
    for row in rows:
        assert set(row) == {"id", "input", "grader", "tags", "expect", "severity", "source"}
        assert row["id"] not in ids, f"təkrarlanan id: {row['id']}"
        ids.add(row["id"])
        assert row["grader"] == "regex_match"
        re.compile(row["expect"]["pattern"])          # pattern qurulur
        assert "CANONICAL.yaml#" in row["source"], row["source"]
        cited = row["source"].split("CANONICAL.yaml#")[1].split(".boundary")[0]
        assert cited in param_ids, cited
        assert "Aurora" not in row["input"] and "ORD-" not in row["input"]


def test_library_probe_points_come_from_the_canonical_table():
    """Case-lər ƏL İLƏ yazılmayıb — hər probe nöqtəsi cədvəldəki nöqtədir."""
    canonical = yaml.safe_load((LIBRARY_CORPUS / "CANONICAL.yaml").read_text(encoding="utf-8"))
    cfg = yaml.safe_load((REPO / "evals" / "datasets" / "corpora" / "library.yaml")
                         .read_text(encoding="utf-8"))
    expected = 0
    for p in canonical["parameters"]:
        if p["id"] in cfg["boundaries"]:
            assert "boundary" in p, p["id"]
            expected += len(p["boundary"]["points"])
    rows = [json.loads(l) for l in LIBRARY_JSONL.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("//")]
    assert len(rows) == expected


# ---------------------------------------------------------------------------
# 4. Etiketlər korpusa aiddir
# ---------------------------------------------------------------------------
def test_label_sets_of_the_two_corpora_do_not_overlap(bf):
    aurora = set(bf.load_corpus("aurora").labels)
    library = set(bf.load_corpus("library").labels)
    assert aurora & library == set(), aurora & library
    assert len(library) >= 10


def test_every_expected_label_has_an_assertion(bf):
    """Konfiqurasiya ilə korpus arasında boşluq qalmasın."""
    for name in ("aurora", "library"):
        cfg = bf.load_corpus(name)
        canonical = cfg.canonical()
        for p in canonical["parameters"]:
            if p["id"] not in cfg.boundaries:
                continue
            for point in p["boundary"]["points"]:
                assert point["expected"] in cfg.labels, (name, p["id"], point)


def test_unknown_macro_is_refused(bf, tmp_path):
    with pytest.raises(ValueError, match="tanınmayan makro"):
        bf._assertion({"macro": "NO_SUCH_MACRO"})


# ---------------------------------------------------------------------------
# 5. Dürüstlük — nə törədilir, nə əl işidir
# ---------------------------------------------------------------------------
def test_config_states_which_blocks_are_derived(bf):
    library = bf.load_corpus("library")
    assert set(library.blocks) <= bf.DERIVED_BLOCKS, (
        "ikinci korpus yalnız TÖRƏDİLƏN bloklarla qaça bilər; əl ilə yazılmış "
        "Aurora blokları köçürülə bilməz və bunu gizlətmək olmaz")
    aurora = bf.load_corpus("aurora")
    assert bf.DERIVED_BLOCKS <= set(aurora.blocks)
    assert len(aurora.blocks) > len(library.blocks)


def test_library_corpus_has_a_deliberately_broken_version_chain():
    """Aurora zənciri bütövdür; üçüncü hesabatın SÜNİ mutasiyadan başqa
    sübutu olsun deyə ikinci korpusa QƏSDƏN qırıq qoyulub (CANONICAL başlığında
    yazılıb). Qırıq itsə, `conflicts.py` §3 yenidən sübutsuz qalır."""
    from target.corpus import conflicts as C
    docs = sorted(LIBRARY_CORPUS.glob("*.md"))
    codes = {i.code for i in C.version_chain(docs)}
    assert "appendix_version_mismatch" in codes
    assert "clause_superseded_date_mismatch" in codes

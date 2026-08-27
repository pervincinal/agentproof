"""`evals/datasets/full.jsonl` üçün struktur validasiyası.

Dataset-in özü də bir artefaktdır və onun da testi olmalıdır. Burada ÜÇ şey
yoxlanılır (dataset-eng.md dizayn qaydaları):

1. **İzlənəbilirlik.** Hər case-in `source`-u korpusda HƏQİQƏTƏN mövcud olan
   tələyə / parametrə / fixture-a işarə etməlidir. İzlənə bilməyən case silinir.
2. **Grader mövcudluğu.** Hər `grader` registry-dədir.
3. **`expect` uyğunluğu.** Hər case öz grader-inə süni cavabla verilir; grader
   `expect` açarını tapmadıqda `require()` ValueError atır. Yəni bu test
   "grader-in gözlədiyi struktur"u sənəddən deyil, GRADER-İN ÖZÜNDƏN alır.

Əlavə olaraq: fayl generatorla sinxrondur (əl ilə redaktə aşkarlanır).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from agentproof.graders import registry
from agentproof.runner.task import load_cases
from agentproof.types import AgentResponse, Case, ToolCall, Usage

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals" / "datasets" / "full.jsonl"
BUILDER = ROOT / "evals" / "datasets" / "build_full.py"
CORPUS = ROOT / "target" / "corpus"

EXPECTED_TOTAL = 150


# ------------------------------------------------------------------ fixtures
@pytest.fixture(scope="module")
def cases() -> list[Case]:
    return load_cases(DATASET)


@pytest.fixture(scope="module")
def corpus_ids() -> dict[str, set[str]]:
    """Korpusda mövcud olan bütün izlənə bilən identifikatorlar."""
    canonical = yaml.safe_load((CORPUS / "CANONICAL.yaml").read_text(encoding="utf-8"))
    fixtures = yaml.safe_load((CORPUS / "FIXTURES.yaml").read_text(encoding="utf-8"))
    traps = (CORPUS / "TRAPS.md").read_text(encoding="utf-8")
    taxonomy = (ROOT / "docs" / "FAILURE-TAXONOMY.md").read_text(encoding="utf-8")
    return {
        # Taksonomiya rejim ID-ləri — yalnız sənəddə BAŞLIQ kimi mövcud olanlar.
        "taxonomy": set(re.findall(r"^### ([RGCSTOL]\d) ", taxonomy, re.MULTILINE)),
        # `CANONICAL.yaml`-ın üst səviyyəli bölmələri (colliding_values, gaps, ...).
        "canonical_section": set(canonical),
        "trap": set(re.findall(r"\bT-\d{2}\b", traps)),
        "boundary": set(re.findall(r"\bB-\d{2}\b", traps)),
        "contradiction": set(re.findall(r"\bC-\d{2}\b", traps)),
        "write": set(re.findall(r"\bW-\d{2}\b", traps)),
        "injection": {p["id"] for p in fixtures["injection_payloads"]},
        "gap": {g["id"] for g in canonical["gaps"]},
        "order": {o["order_id"] for o in fixtures["orders"]},
        "scenario": {s["id"] for s in fixtures["standalone_scenarios"]},
        "parameter": {p["id"] for p in canonical["parameters"]},
        "document": {d["file"] for d in canonical["meta"]["documents"]},
    }


TOKEN_PATTERNS = {
    "trap": r"\bT-\d{2}\b",
    "boundary": r"\bB-\d{2}\b",
    "contradiction": r"\bC-\d{2}\b",
    "write": r"\bW-\d{2}\b",
    "injection": r"\bINJ-\d{2}\b",
    "gap": r"\bGAP-\d{2}\b",
    "order": r"\bORD-\d{5}\b",
    "scenario": r"\bSC-\d{2}\b",
    "document": r"\b[a-z-]+\.md\b",
}


# ------------------------------------------------------------------- ölçü/forma
def test_case_count(cases: list[Case]) -> None:
    assert len(cases) == EXPECTED_TOTAL, (
        f"{len(cases)} case var, {EXPECTED_TOTAL} gözlənilir — paylama dəyişibsə "
        "COVERAGE.md cədvəli də yenilənməlidir"
    )


def test_ids_unique_and_slugged(cases: list[Case]) -> None:
    ids = [c.id for c in cases]
    assert len(set(ids)) == len(ids)
    bad = [i for i in ids if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", i)]
    assert not bad, f"case id-ləri kiçik hərf/slug olmalıdır: {bad}"


def test_every_case_has_tags_and_severity(cases: list[Case]) -> None:
    assert all(c.tags for c in cases)
    assert all(c.severity in {"low", "medium", "high"} for c in cases)


def test_dataset_is_in_sync_with_generator() -> None:
    """`full.jsonl` əl ilə redaktə edilibsə bu test qırmızıya düşür."""
    result = subprocess.run(
        [sys.executable, str(BUILDER), "--check"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


# ------------------------------------------------------------- izlənəbilirlik
def test_every_source_is_traceable(cases: list[Case], corpus_ids: dict[str, set[str]]) -> None:
    """Hər `source` ən azı BİR mövcud korpus identifikatoruna bağlanmalıdır."""
    untraceable: list[str] = []
    unknown: list[str] = []
    for case in cases:
        hits = 0
        for kind, pattern in TOKEN_PATTERNS.items():
            for token in re.findall(pattern, case.source):
                if kind == "document" and token in {"TRAPS.md", "FIXTURES.yaml",
                                                    "CANONICAL.yaml", "TOOLS.md",
                                                    "FAILURE-TAXONOMY.md", "COVERAGE.md"}:
                    continue
                if token in corpus_ids[kind]:
                    hits += 1
                else:
                    unknown.append(f"{case.id}: {kind} {token!r} korpusda yoxdur")
        # `CANONICAL.yaml#<parametr>` / `CANONICAL.yaml#<bölmə>[<parametr>]`
        for token in re.findall(r"CANONICAL\.yaml#([a-z_]+)(?:\[([a-z_]+)\])?", case.source):
            for value, key in ((token[0], "parameter"), (token[0], "canonical_section"),
                               (token[1], "parameter")):
                if value and value in corpus_ids[key]:
                    hits += 1
        # `FAILURE-TAXONOMY.md#<rejim>` istinadları
        for mode in re.findall(r"FAILURE-TAXONOMY\.md#([RGCSTOL]\d)", case.source):
            if mode in corpus_ids["taxonomy"]:
                hits += 1
        if hits == 0:
            untraceable.append(f"{case.id}: source={case.source!r}")
    assert not unknown, "korpusda olmayan identifikatora istinad:\n  " + "\n  ".join(unknown)
    assert not untraceable, (
        "izlənə bilməyən case (dataset-eng.md: silinir):\n  " + "\n  ".join(untraceable)
    )


def test_boundary_block_covers_all_36_canonical_boundaries(cases: list[Case]) -> None:
    canonical = yaml.safe_load((CORPUS / "CANONICAL.yaml").read_text(encoding="utf-8"))
    with_boundary = {p["id"] for p in canonical["parameters"] if "boundary" in p}
    probed = {
        m.group(1)
        for c in cases if "boundary" in c.tags
        for m in [re.search(r"CANONICAL\.yaml#([a-z_]+)\.boundary", c.source)] if m
    }
    assert probed == with_boundary, (
        "sərhəd probe-u olmayan parametr(lər): "
        f"{sorted(with_boundary - probed)}; artıq: {sorted(probed - with_boundary)}"
    )


def test_stale_clause_block_has_both_directions(cases: list[Case]) -> None:
    """T-01 tipi (bayat səxavətli) VƏ T-07 tipi (cari səxavətli) — hər ikisi lazımdır.

    Yalnız bir istiqamət ölçülsəydi, "həmişə ən yeni rəqəmi seç" strategiyası
    100% alardı və biz onu bacarıq sanardıq (TRAPS.md §2.4).
    """
    a = [c for c in cases if "stale-generous" in c.tags]
    b = [c for c in cases if "current-generous" in c.tags]
    assert len(a) >= 8, f"stale-generous istiqaməti çox azdır: {len(a)}"
    assert len(b) >= 8, f"current-generous istiqaməti çox azdır: {len(b)}"


def test_baseline_cases_exist(cases: list[Case]) -> None:
    """Yalnız uğursuzluqlardan ibarət dataset reqressiya ölçə bilmir."""
    baseline = [c for c in cases if "baseline" in c.tags]
    assert len(baseline) >= 20, f"baseline case sayı azdır: {len(baseline)}"


def test_multilingual_pairs_are_symmetric(cases: list[Case]) -> None:
    az = {c.id[len("l1-az-"):] for c in cases if c.id.startswith("l1-az-")}
    ru = {c.id[len("l1-ru-"):] for c in cases if c.id.startswith("l1-ru-")}
    assert az and az == ru, f"AZ/RU cütləri simmetrik deyil: {az ^ ru}"


def test_pairwise_block_covers_all_pairs() -> None:
    """`Boşluq 2` iddiası SAYILIR, iddia edilmir."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_full", BUILDER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    rows = module.generate_pairwise()
    got, total = module.verify_pairwise(rows)
    assert got == total == 100, f"pairwise əhatə {got}/{total}"


# ------------------------------------------------------------ grader müqaviləsi
def test_every_grader_is_registered(cases: list[Case]) -> None:
    unknown = sorted({c.grader for c in cases if c.grader not in registry.names()})
    assert not unknown, f"registry-də olmayan grader(lər): {unknown}"


def _probe_response() -> AgentResponse:
    """Süni cavab — məzmunu əhəmiyyətsizdir, yalnız STRUKTUR yoxlanır."""
    return AgentResponse(
        text='{"order_id": "ORD-10001", "note": "14 days"}',
        tool_calls=[ToolCall(name="check_return_eligibility", arguments={"order_id": "X"})],
        retrieved=[],
        usage=Usage(input_tokens=10, output_tokens=10, model="claude-sonnet-4-5"),
        latency_ms=100,
    )


def test_expect_structure_matches_grader_contract(cases: list[Case]) -> None:
    """`expect` grader-in TƏLƏB ETDİYİ açarları daşıyır.

    Grader-lər `require()` ilə çatışmayan açarda ValueError atır — yəni bu test
    müqaviləni sənəddən deyil, kodun özündən oxuyur və sənəd köhnəldikdə də
    doğru qalır.
    """
    response = _probe_response()
    problems: list[str] = []
    for case in cases:
        grader = registry.get(case.grader)
        try:
            if registry.kind(case.grader) == "judge":
                grader.build_prompt(case, response.text)  # type: ignore[union-attr]
            elif registry.is_aggregate(case.grader):
                grader.grade_many(case, [response, response])  # type: ignore[union-attr]
            else:
                grader.grade(case, response)  # type: ignore[union-attr]
        except (ValueError, KeyError, TypeError) as exc:
            problems.append(f"{case.id} ({case.grader}): {exc}")
    assert not problems, "`expect` grader müqaviləsinə uyğun deyil:\n  " + "\n  ".join(problems)


def test_regex_patterns_compile(cases: list[Case]) -> None:
    bad = []
    for case in cases:
        for key in ("pattern",):
            if key in case.expect:
                try:
                    re.compile(str(case.expect[key]))
                except re.error as exc:
                    bad.append(f"{case.id}: {exc}")
        for pattern in case.expect.get("leak_patterns", []):
            try:
                re.compile(str(pattern))
            except re.error as exc:
                bad.append(f"{case.id}: {exc}")
    assert not bad, bad


def test_no_case_asserts_two_things(cases: list[Case]) -> None:
    """Bir case bir şey ölçür — `contains_all` + `contains_none` eyni anda olmaz."""
    both = [c.id for c in cases if "all" in c.expect and "none" in c.expect]
    assert not both, f"iki ayrı iddianı yoxlayan case(lər): {both}"


# --------------------------------------------------------------- gold lövbərlər
def test_retrieval_cases_use_stable_anchors() -> None:
    """XAM dataset faylında gold-lar UUID DEYİL, `doc#clause` lövbərləridir.

    UUID-lər yenidən indeksləmədə dəyişir — dataset-də saxlanılsalar, bilik
    bazası hər yenidən qurulanda bütün retrieval case-ləri səssizcə sınardı.
    """
    uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-", re.IGNORECASE)
    raw_gold: list[str] = []
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("//"):
            continue
        raw_gold += [str(g) for g in json.loads(line).get("expect", {}).get("gold_chunks", [])]
    assert raw_gold, "retrieval case-i yoxdur — test mənasız yaşıl olardı"
    assert not [g for g in raw_gold if uuid_re.match(g)], (
        f"dataset-də xam segment UUID-i var: {[g for g in raw_gold if uuid_re.match(g)]}"
    )
    from target.corpus.anchors import is_anchor

    not_anchors = [g for g in raw_gold if not is_anchor(g)]
    assert not not_anchors, f"lövbər sintaksisinə uyğun olmayan gold: {not_anchors}"


def test_anchors_resolve_to_segment_ids(cases: list[Case]) -> None:
    """`load_cases()` lövbərləri həqiqi segment id-lərinə çevirir (xəritə mövcuddur)."""
    uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", re.IGNORECASE)
    resolved = [c for c in cases if c.expect.get("gold_chunks")]
    assert resolved, "retrieval case-i tapılmadı"
    for case in resolved:
        assert case.expect["_gold_anchors"], f"{case.id}: lövbər izi itdi"
        for chunk in case.expect["gold_chunks"]:
            assert uuid_re.match(chunk), (
                f"{case.id}: lövbər segment id-yə çevrilməyib: {chunk!r} — "
                "`python target/corpus/anchors.py build` qaçırılıb?"
            )

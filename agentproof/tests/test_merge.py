"""AP-042 — əvəz olunan (superseded) nəticələr ikiqat sayılmır.

Real hadisə: `full-run-03`-də 25 case `skipped` bitdi (kredit tükəndi), həmin
25 case `full-run-03b`-də uğurla qaçdı. İki qaçış birlikdə oxunanda alət 187
case göstərirdi (162 + 25) və hesabatda "25 ölçülmədi" yazırdı.

Bu testlər həmin sayma qaydasını qoruyur: ən son qaçış götürülür, əvvəlki
SİLİNMİR — `superseded` kimi sayılır.
"""

from __future__ import annotations

import pytest

from agentproof.report import reproduction as R
from agentproof.report.merge import (
    MergeItem,
    RunOrigin,
    merge_items,
    merge_records,
    parse_moment,
    render_merge_notes,
)
from agentproof.types import (
    AgentResponse,
    Case,
    CaseResult,
    GradeResult,
    RunRecord,
)

EARLY = "2026-08-27T20:57:16+00:00"
LATE = "2026-08-28T09:33:31+00:00"


# --------------------------------------------------------------- köməkçilər
def _origin(
    run_id: str,
    started_at: str,
    dataset_hash: str = "h1",
    full_dataset_hash: str = "",
) -> RunOrigin:
    return RunOrigin(
        run_id=run_id,
        started_at=started_at,
        dataset_hash=dataset_hash,
        full_dataset_hash=full_dataset_hash,
    )


def _case(case_id: str, needles=("alpha", "beta")) -> dict:
    return Case(
        id=case_id,
        input="sual",
        grader="contains_all",
        expect={"all": list(needles)},
        severity="high",
        tags=["policy"],
    ).to_dict()


def _resp(text: str = "alpha beta", error: str | None = None) -> AgentResponse:
    return AgentResponse(text=text, error=error)


def _sample(case_id: str, origin: RunOrigin, *, ok: bool = True, broken: bool = False):
    """`from_log_samples()` üçün bir nümunə: 3 cəhd."""
    if broken:
        responses = [_resp("", error="credit_exhausted")] * 3
    else:
        responses = [_resp("alpha beta" if ok else "yalnız alpha")] * 3
    return (_case(case_id), responses, origin)


def _result(case_id: str, *, passed=True, skipped=False, cost=0.01, latency=100):
    return CaseResult(
        case_id=case_id,
        response=_resp(),
        grade=GradeResult(
            passed=passed and not skipped,
            score=1.0 if passed else 0.0,
            grader="contains_all",
            reason="" if passed and not skipped else "sındı",
            skipped=skipped,
        ),
        cost_usd=None if skipped else cost,
        latency_ms=latency,
        attempt=3,
        severity="high",
    )


def _record(
    results,
    run_id="r1",
    started_at=EARLY,
    dataset_hash="h1",
    totals=None,
    full_dataset_hash="",
):
    graded = [r for r in results if not r.grade.skipped]
    return RunRecord(
        run_id=run_id,
        target="mock",
        target_version="1.0",
        model="m",
        dataset_hash=dataset_hash,
        full_dataset_hash=full_dataset_hash,
        started_at=started_at,
        results=list(results),
        totals=totals
        if totals is not None
        else {
            "n_cases": len(results),
            "pass_rate": (sum(1 for r in graded if r.grade.passed) / len(graded))
            if graded
            else 0.0,
            "cost_usd": sum(r.cost_usd or 0.0 for r in results),
            "wasted_cost_usd": 0.0,
        },
        # Sahəni DAŞIYAN qeyd tərifə görə sxem 4-dür; daşımayan — köhnə 3.
        schema_version=4 if full_dataset_hash else 3,
    )


# ------------------------------------------------- tələb 5: əvəzləmə qaydası
def test_skipped_then_successful_counts_as_successful():
    """AP-042-nin əsl hadisəsi: kredit bitdi -> skipped, sonra uğurlu qaçdı."""
    report = R.from_log_samples(
        [
            _sample("c1", _origin("run-a", EARLY), broken=True),
            _sample("c1", _origin("run-b", LATE), ok=True),
        ]
    )
    assert len(report.verdicts) == 1
    assert report.verdicts[0].classification == R.STABLE_PASS
    assert report.counts[R.SKIPPED] == 0
    # Vahid NƏTİCƏDİR: bir qaçışın bir case üçün verdiyi nəticə (cəhd yox).
    assert report.n_superseded == 1
    assert report.superseded[0].case_id == "c1"
    assert report.superseded[0].origin.run_id == "run-a"
    assert report.superseded[0].superseded_by.run_id == "run-b"


def test_successful_then_skipped_takes_the_LAST_not_the_BEST():
    """Seçim qaydası ZAMANDIR, nəticə deyil.

    "Uğurlusunu üstün tut" qaydası sonrakı reqressiyanı gizlədərdi: case dünən
    keçib, bu gün ümumiyyətlə ölçülməyibsə, hesabat "keçdi" deməməlidir.
    """
    report = R.from_log_samples(
        [
            _sample("c1", _origin("run-a", EARLY), ok=True),
            _sample("c1", _origin("run-b", LATE), broken=True),
        ]
    )
    assert len(report.verdicts) == 1
    assert report.verdicts[0].classification == R.SKIPPED
    assert report.n_superseded == 1
    assert report.superseded[0].superseded_by.run_id == "run-b"


def test_different_dataset_hashes_are_not_merged():
    """Eyni id, fərqli dataset -> birləşmə YOX, açıq xəbərdarlıq."""
    report = R.from_log_samples(
        [
            _sample("c1", _origin("run-a", EARLY, dataset_hash="aaa")),
            _sample("c1", _origin("run-b", LATE, dataset_hash="bbb")),
        ]
    )
    assert len(report.verdicts) == 2          # birləşmədi
    assert report.n_superseded == 0
    assert any("FƏRQLİ dataset_hash" in w for w in report.warnings)
    assert "BİRLƏŞMƏ XƏBƏRDARLIĞI" in R.render_text(report)


def test_cross_dataset_merge_needs_the_flag_and_verifies_the_case_text():
    """`--merge-across-datasets`: hash fərqli, amma case TƏRİFİ eynidirsə birləşir."""
    report = R.from_log_samples(
        [
            _sample("c1", _origin("run-a", EARLY, dataset_hash="aaa"), broken=True),
            _sample("c1", _origin("run-b", LATE, dataset_hash="bbb"), ok=True),
        ],
        allow_cross_dataset=True,
    )
    assert len(report.verdicts) == 1
    assert report.verdicts[0].classification == R.STABLE_PASS
    assert report.n_superseded == 1
    assert any("barmaq izi" in w for w in report.warnings)


def test_cross_dataset_merge_refuses_when_the_case_text_differs():
    """Eyni id, fərqli sual — bayraq verilsə də birləşmir (səssiz korlanma)."""
    early = (_case("c1", needles=("alpha",)), [_resp()] * 3,
             _origin("run-a", EARLY, dataset_hash="aaa"))
    late = (_case("c1", needles=("gamma",)), [_resp()] * 3,
            _origin("run-b", LATE, dataset_hash="bbb"))
    report = R.from_log_samples([early, late], allow_cross_dataset=True)
    assert len(report.verdicts) == 2
    assert report.n_superseded == 0
    assert any("case TƏRİFİ" in w for w in report.warnings)


def test_superseded_count_is_visible_in_the_summary_and_json():
    report = R.from_log_samples(
        [
            _sample("c1", _origin("run-a", EARLY), broken=True),
            _sample("c1", _origin("run-b", LATE), ok=True),
            _sample("c2", _origin("run-a", EARLY), ok=True),
        ]
    )
    text = R.render_text(report)
    assert "case: 2 · əvəz olunmuş nəticə: 1" in text
    assert "superseded        1" in text
    data = report.to_dict()
    assert data["n_superseded"] == 1
    assert data["superseded"][0]["superseded_by"]["run_id"] == "run-b"
    # artefaktdan geri oxunanda da itmir (hesabat qatı təsnifatı yenidən aparmır)
    back = R.report_from_dict(data)
    assert back.n_superseded == 1
    assert back.superseded[0].case_id == "c1"


def test_case_count_matches_the_dataset_after_the_merge():
    """Tələb 4: `case:` sayı faktiki case sayı ilə uzlaşır, ikiqat saymır."""
    samples = [_sample(f"c{i}", _origin("run-a", EARLY), ok=True) for i in range(5)]
    samples += [_sample(f"c{i}", _origin("run-b", LATE), ok=True) for i in range(2)]
    report = R.from_log_samples(samples)
    assert len(report.verdicts) == 5
    assert report.n_superseded == 2


def test_equal_timestamps_stay_independent_attempts():
    """Sıralana bilməyən qaçışlar əvəz olunmur — 3 müstəqil qaçış = 3 cəhd."""
    items = [
        MergeItem("c1", _origin("r1", EARLY), payload=1),
        MergeItem("c1", _origin("r2", EARLY), payload=2),
    ]
    outcome = merge_items(items)
    assert len(outcome.cases) == 1
    assert outcome.cases[0].items == [1, 2]
    assert outcome.n_superseded == 0


def test_an_undated_run_never_supersedes_and_says_so():
    items = [
        MergeItem("c1", _origin("r1", ""), payload=1),
        MergeItem("c1", _origin("r2", LATE), payload=2),
    ]
    outcome = merge_items(items)
    assert outcome.n_superseded == 0
    assert any("tarix yoxdur" in w for w in outcome.warnings)


def test_supersede_can_be_switched_off_for_independent_runs():
    items = [
        MergeItem("c1", _origin("r1", EARLY), payload=1),
        MergeItem("c1", _origin("r2", LATE), payload=2),
    ]
    outcome = merge_items(items, supersede=False)
    assert outcome.cases[0].items == [1, 2]
    assert outcome.n_superseded == 0


def test_file_order_does_not_decide_the_winner():
    """Arqument sırası dəyişəndə nəticə DƏYİŞMİR — qərar tarixindir."""
    a = MergeItem("c1", _origin("r-early", EARLY), payload="köhnə")
    b = MergeItem("c1", _origin("r-late", LATE), payload="yeni")
    assert merge_items([a, b]).cases[0].items == ["yeni"]
    assert merge_items([b, a]).cases[0].items == ["yeni"]


@pytest.mark.parametrize(
    "value, ok",
    [
        ("2026-08-28T09:33:31+00:00", True),
        ("2026-08-27T00:00:00Z", True),
        ("2026-08-27T00:00:00", True),   # zolaqsız -> UTC sayılır
        ("", False),
        ("dünən", False),
    ],
)
def test_moment_parsing(value, ok):
    assert (parse_moment(value) is not None) is ok


# ------------------------------------------------ RunRecord birləşməsi (AP-013)
def test_merge_records_produces_one_verdict_per_case():
    early = _record(
        [_result("c1"), _result("c2", skipped=True)], run_id="r1", started_at=EARLY
    )
    late = _record([_result("c2", passed=True)], run_id="r2", started_at=LATE)
    merged, outcome = merge_records([early, late])

    assert len(merged.results) == 2
    assert {r.case_id for r in merged.results} == {"c1", "c2"}
    assert merged.totals["n_cases"] == 2
    assert merged.totals["n_skipped"] == 0
    assert merged.totals["pass_rate"] == 1.0
    assert merged.totals["merge"]["n_superseded"] == 1
    assert merged.totals["merge"]["superseded_case_ids"] == ["c2"]
    assert outcome.n_superseded == 1


def test_merge_records_keeps_the_spend_even_though_costs_are_recomputed():
    """`cost_usd` qalib nəticələrə görədir; ödənilən məbləğ ayrıca qalır."""
    early = _record([_result("c1", cost=1.0)], run_id="r1", started_at=EARLY)
    late = _record([_result("c1", cost=2.0)], run_id="r2", started_at=LATE)
    merged, _ = merge_records([early, late])
    assert merged.totals["cost_usd"] == 2.0
    assert merged.totals["merge"]["spent_including_superseded_usd"] == 3.0


def test_merge_records_clears_halted_when_the_rerun_completed_the_run():
    early = _record(
        [_result("c1", skipped=True)],
        run_id="r1",
        started_at=EARLY,
        totals={
            "pass_rate": 0.0,
            "cost_usd": 0.0,
            "halted": {"halted": True, "reason": "credit_exhausted", "case_id": "c1"},
        },
    )
    late = _record([_result("c1")], run_id="r2", started_at=LATE)
    merged, _ = merge_records([early, late])
    assert merged.totals["halted"]["halted"] is False
    assert "dayandırılmışdı" in merged.totals["halted"]["detail"]


def test_merge_records_keeps_halted_when_cases_are_still_unmeasured():
    early = _record(
        [_result("c1", skipped=True), _result("c2", skipped=True)],
        run_id="r1",
        started_at=EARLY,
        totals={
            "pass_rate": 0.0,
            "cost_usd": 0.0,
            "halted": {"halted": True, "reason": "credit_exhausted", "case_id": "c1"},
        },
    )
    late = _record([_result("c1")], run_id="r2", started_at=LATE)
    merged, _ = merge_records([early, late])
    assert merged.totals["halted"]["halted"] is True


def test_merged_run_id_is_deterministic():
    early = _record([_result("c1")], run_id="r1", started_at=EARLY)
    late = _record([_result("c1")], run_id="r2", started_at=LATE)
    first, _ = merge_records([early, late])
    second, _ = merge_records([late, early])
    assert first.run_id == second.run_id
    assert first.run_id.startswith("merge-")


def test_merge_records_refuses_an_empty_input():
    with pytest.raises(ValueError):
        merge_records([])


def test_merge_records_warns_when_dataset_hashes_differ():
    early = _record([_result("c1")], run_id="r1", started_at=EARLY, dataset_hash="aaa")
    late = _record([_result("c2")], run_id="r2", started_at=LATE, dataset_hash="bbb")
    merged, outcome = merge_records([early, late])
    assert merged.dataset_hash == "bbb"
    assert merged.totals["merge"]["dataset_hashes"] == ["aaa", "bbb"]
    assert any("dataset_hash" in w for w in outcome.warnings)


def test_render_merge_notes_names_the_replacement():
    early = _record([_result("c1", skipped=True)], run_id="r1", started_at=EARLY)
    late = _record([_result("c1")], run_id="r2", started_at=LATE)
    _, outcome = merge_records([early, late])
    text = render_merge_notes(outcome)
    assert "SİLİNMƏDİ" in text
    assert "r1" in text and "r2" in text


def test_merge_reads_old_schema_records_without_breaking():
    """Sxem 1/2 artefaktları (yeni sahələr YOX) birləşmədə oxunmağa davam edir.

    Cari baseline məhz belədir: `full-run-03` sxem 2, `full-run-03b` sxem 3.
    """
    old = {
        "run_id": "r1",
        "target": "dify_http",
        "dataset_hash": "h1",
        "started_at": EARLY,
        "results": [
            {
                "case_id": "c1",
                "response": {"text": "alpha beta"},
                "grade": {"passed": True, "score": 1.0, "grader": "contains_all"},
                "cost_usd": 0.5,
            }
        ],
        "totals": {"pass_rate": 1.0, "cost_usd": 0.5},
    }
    new = dict(old, run_id="r2", started_at=LATE, schema_version=3)
    merged, outcome = merge_records(
        [RunRecord.from_dict(old), RunRecord.from_dict(new)]
    )
    assert merged.schema_version == 3          # ən yüksək mənbə sxemi
    assert merged.totals["n_cases"] == 1
    assert outcome.n_superseded == 1
    # köhnə artefaktda `cost_coverage` yoxdur — bu, gizlədilmir, qeyddə yazılır
    note = merged.totals["cost_coverage"]["note"]
    assert merged.totals["cost_coverage"]["reconstructed"] is True
    assert "köhnə sxem" in note and "r1" in note


# --------------------------------- AP-042: dataset-in İKİ imzası (sxem 4)
# `dataset_hash` filtrdən SONRAKI dəsti imzalayır, ona görə `--filter` ilə
# qaçırılan təkrar qaçış həmişə "başqa dataset" kimi görünürdü və birləşmə
# `--merge-across-datasets` tələb edirdi. `full_dataset_hash` dataset FAYLINI
# imzalayır — uyğunluq açarı odur.
FULL = "e60c825c84bbda8a"


def test_filtered_rerun_merges_without_the_escape_hatch():
    """Əsl hadisə: 162-lik qaçış + həmin 25-in `--filter` ilə təkrarı.

    Seçim imzaları FƏRQLİ (162 case vs 25 case), dataset faylı EYNİ. Bayraqsız
    birləşməlidir — köhnə davranışda bu, `--merge-across-datasets` tələb edirdi.
    """
    report = R.from_log_samples(
        [
            _sample("c1", _origin("run-a", EARLY, "sel-162", FULL), broken=True),
            _sample("c1", _origin("run-b", LATE, "sel-25", FULL), ok=True),
        ]
    )
    assert len(report.verdicts) == 1          # birləşdi
    assert report.verdicts[0].classification == R.STABLE_PASS
    assert report.n_superseded == 1
    assert report.warnings == []              # xəbərdarlıq da lazım deyil


def test_different_full_dataset_hashes_are_still_blocked():
    """Dataset faylı HƏQİQƏTƏN dəyişibsə sərhəd yerində qalır."""
    report = R.from_log_samples(
        [
            _sample("c1", _origin("run-a", EARLY, "sel-1", "full-aaa")),
            _sample("c1", _origin("run-b", LATE, "sel-2", "full-bbb")),
        ]
    )
    assert len(report.verdicts) == 2
    assert report.n_superseded == 0
    warning = next(w for w in report.warnings if "FƏRQLİ dataset_hash" in w)
    assert "TAM dataset imzası" in warning


def test_full_dataset_hash_is_used_only_when_every_run_has_it():
    """Bir mənbədə tam imza yoxdursa (sxem <= 3) HAMISI köhnə açara qayıdır.

    Yarım-yarım müqayisə — birində dataset versiyası, digərində seçilmiş alt
    dəst — iki fərqli kəmiyyəti eyni açar kimi göstərmək olardı.
    """
    report = R.from_log_samples(
        [
            _sample("c1", _origin("run-a", EARLY, "sel-162", FULL)),
            _sample("c1", _origin("run-b", LATE, "sel-25")),   # köhnə artefakt
        ]
    )
    assert len(report.verdicts) == 2          # birləşmədi — sərhəd köhnə qaydadadır
    warning = next(w for w in report.warnings if "FƏRQLİ dataset_hash" in w)
    assert "SEÇİM imzası" in warning
    assert "sxem <= 3" in warning


def test_same_selection_hash_still_merges_across_old_artifacts():
    """Sxem <= 3 davranışı DƏYİŞMİR: eyni seçim imzası birləşməyə davam edir."""
    report = R.from_log_samples(
        [
            _sample("c1", _origin("run-a", EARLY, "sel-25"), broken=True),
            _sample("c1", _origin("run-b", LATE, "sel-25"), ok=True),
        ]
    )
    assert len(report.verdicts) == 1
    assert report.n_superseded == 1


def test_merge_records_prefers_the_full_dataset_hash_as_the_key():
    early = _record(
        [_result("c1", skipped=True), _result("c2")],
        run_id="r1", started_at=EARLY, dataset_hash="sel-162", full_dataset_hash=FULL,
    )
    late = _record(
        [_result("c1")],
        run_id="r2", started_at=LATE, dataset_hash="sel-25", full_dataset_hash=FULL,
    )
    merged, outcome = merge_records([early, late])

    assert merged.totals["n_cases"] == 2          # c1 İKİ dəfə sayılmadı
    assert outcome.n_superseded == 1
    assert merged.totals["n_skipped"] == 0        # skipped nəticə əvəz olundu
    # Seçim imzaları fərqlidir, amma bu, ARTIQ xəbərdarlıq deyil.
    assert outcome.warnings == []
    merge = merged.totals["merge"]
    assert merge["compatibility_key"] == "full_dataset_hash"
    assert merge["dataset_hashes"] == ["sel-162", "sel-25"]
    assert merge["full_dataset_hashes"] == [FULL]
    # Birləşmiş qeyd hər iki imzanı daşıyır; seçim imzası case dəstini TAM
    # əhatə edən qaçışdan gəlir (162-lik), tam imza isə dataset versiyasıdır.
    assert merged.dataset_hash == "sel-162"
    assert merged.full_dataset_hash == FULL
    assert merged.schema_version == 4


def test_merge_records_warns_when_full_dataset_hashes_differ():
    early = _record([_result("c1")], run_id="r1", started_at=EARLY,
                    dataset_hash="s1", full_dataset_hash="full-aaa")
    late = _record([_result("c2")], run_id="r2", started_at=LATE,
                   dataset_hash="s2", full_dataset_hash="full-bbb")
    merged, outcome = merge_records([early, late])
    assert merged.totals["merge"]["compatibility_key"] == "full_dataset_hash"
    assert merged.totals["merge"]["full_dataset_hashes"] == ["full-aaa", "full-bbb"]
    warning = next(w for w in outcome.warnings if "dataset imzası" in w)
    assert "full_dataset_hash" in warning
    assert "full-aaa" in warning and "full-bbb" in warning


def test_merge_sources_record_both_signatures():
    early = _record([_result("c1")], run_id="r1", started_at=EARLY,
                    dataset_hash="sel-162", full_dataset_hash=FULL)
    late = _record([_result("c2")], run_id="r2", started_at=LATE,
                   dataset_hash="sel-25", full_dataset_hash=FULL)
    merged, _ = merge_records([early, late], sources=["a.json", "b.json"])
    sources = merged.totals["merge"]["sources"]
    assert [s["dataset_hash"] for s in sources] == ["sel-162", "sel-25"]
    assert [s["full_dataset_hash"] for s in sources] == [FULL, FULL]


def test_schema_3_record_has_no_full_dataset_hash():
    """Köhnə artefaktda sahə YOXDUR -> `""` (ölçülmədi), uydurulmur."""
    old = {
        "schema_version": 3,
        "run_id": "r1",
        "target": "dify_http",
        "dataset_hash": "sel-25",
        "started_at": EARLY,
        "results": [],
        "totals": {},
    }
    record = RunRecord.from_dict(old)
    assert record.dataset_hash == "sel-25"
    assert record.full_dataset_hash == ""      # `dataset_hash` BURA kopyalanmır
    assert record.to_dict()["full_dataset_hash"] == ""

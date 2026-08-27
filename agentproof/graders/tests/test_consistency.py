"""consistency_at_k (aqreqat grader)"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentproof.graders import registry
from agentproof.types import Case

STABLE = "Qaytarma pəncərəsi 30 gündür, restocking haqqı 15%-dir."
STABLE_REWORDED = "Restocking haqqı 15%, qaytarma pəncərəsi isə 30 gündür."
DRIFTED = "Qaytarma pəncərəsi 45 gündür, restocking haqqı 20%-dir."

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).parent / "fixtures" / "pilot_c1_t07_consistency.json"
PILOT_DATASET = REPO_ROOT / "evals" / "datasets" / "pilot-consistency.jsonl"


def _grade(case, responses):
    return registry.get("consistency_at_k").grade_many(case, responses)


# ------------------------------------------------------------- səth rejimləri
def test_consistency_passes_when_all_answers_agree(make_case, make_response):
    result = _grade(
        make_case("consistency_at_k", {"mode": "numbers", "min_agreement": 1.0}),
        [make_response(text=STABLE) for _ in range(3)],
    )
    assert result.passed
    assert result.score == 1.0


def test_consistency_fails_when_numbers_drift(make_case, make_response):
    """Eyni sual, fərqli siyasət rəqəmi — reliability tədqiqatının əsas ölçüsü."""
    result = _grade(
        make_case("consistency_at_k", {"mode": "numbers", "min_agreement": 1.0}),
        [make_response(text=STABLE), make_response(text=STABLE), make_response(text=DRIFTED)],
    )
    assert not result.passed
    assert result.score == 2 / 3
    assert result.evidence["n_variants"] == 2
    assert result.reason


def test_numbers_mode_ignores_pure_rewording(make_case, make_response):
    """Eyni faktlar, fərqli cümlə quruluşu — `numbers` rejimində sabit sayılır."""
    result = _grade(
        make_case("consistency_at_k", {"mode": "numbers"}),
        [make_response(text=STABLE), make_response(text=STABLE_REWORDED)],
    )
    assert result.passed


def test_normalized_mode_is_stricter_than_numbers(make_case, make_response):
    """Eyni giriş, `normalized` rejimi yenidən ifadələnməni sınıq sayır."""
    responses = [make_response(text=STABLE), make_response(text=STABLE_REWORDED)]
    assert not _grade(make_case("consistency_at_k", {"mode": "normalized"}), responses).passed


def test_key_facts_mode(make_case, make_response):
    expect = {"mode": "key_facts", "key_facts": ["30 gün", "15%"]}
    assert _grade(
        make_case("consistency_at_k", expect),
        [make_response(text=STABLE), make_response(text=STABLE_REWORDED)],
    ).passed
    assert not _grade(
        make_case("consistency_at_k", expect),
        [make_response(text=STABLE), make_response(text=DRIFTED)],
    ).passed


def test_key_facts_mode_requires_key_facts(make_case, make_response):
    with pytest.raises(ValueError, match="key_facts"):
        _grade(
            make_case("consistency_at_k", {"mode": "key_facts"}),
            [make_response(text=STABLE), make_response(text=STABLE)],
        )


def test_consistency_skips_with_single_response(make_case, make_response):
    """`--repeat` verilməyibsə səssizcə keçmir — açıq `skipped`."""
    result = _grade(make_case("consistency_at_k", {}), [make_response(text=STABLE)])
    assert result.skipped
    assert "--repeat" in result.reason


def test_consistency_threshold_below_one(make_case, make_response):
    """3 cavabdan 2-si eynidirsə, 0.6 həddi keçir, 0.9 keçmir."""
    responses = [make_response(text=STABLE), make_response(text=STABLE), make_response(text=DRIFTED)]
    assert _grade(make_case("consistency_at_k", {"min_agreement": 0.6}), responses).passed
    assert not _grade(make_case("consistency_at_k", {"min_agreement": 0.9}), responses).passed


def test_registry_marks_consistency_as_aggregate():
    assert registry.is_aggregate("consistency_at_k")
    assert not registry.is_aggregate("contains_all")


# ------------------------------------------------- normallaşdırma qatının təsiri
def test_surface_form_no_longer_counts_as_disagreement(make_case, make_response):
    """PİLOTUN SINIĞI, kiçildilmiş halda: `24 months` vs `24-month` vs `24 mo`."""
    expect = {"mode": "key_facts", "key_facts": ["24 month"]}
    responses = [
        make_response(text="The warranty is 24 months."),
        make_response(text="It carries a 24-month warranty."),
        make_response(text="Warranty: 24 mo."),
    ]
    result = _grade(make_case("consistency_at_k", expect), responses)
    assert result.passed
    assert result.score == 1.0


def test_incidental_dates_do_not_create_variance(make_case, make_response):
    """Bugünkü/hesablanmış tarix qərar deyil — `numbers` imzasına düşməməlidir."""
    responses = [
        make_response(text="Coverage is 24 months, so it ends 2026-09-01."),
        make_response(text="Coverage is 24 months, so it ends 2026-09-02."),
    ]
    assert _grade(make_case("consistency_at_k", {"mode": "numbers"}), responses).passed


def test_numbers_mode_still_catches_a_policy_number_change(make_case, make_response):
    """Bilərəkdən SINAN: tarix filtri əsl rəqəm dəyişməsini gizlətməməlidir."""
    responses = [
        make_response(text="Coverage is 24 months, so it ends 2026-09-01."),
        make_response(text="Coverage is 18 months, so it ends 2026-03-01."),
    ]
    assert not _grade(make_case("consistency_at_k", {"mode": "numbers"}), responses).passed


def test_numbers_mode_ignores_how_many_times_a_fact_is_repeated(make_case, make_response):
    """Eyni rəqəmi iki dəfə demək fakt fərqi deyil — imza DƏSTdir."""
    responses = [
        make_response(text="It is 24 months. Yes, 24 months in total."),
        make_response(text="It is 24 months."),
    ]
    assert _grade(make_case("consistency_at_k", {"mode": "numbers"}), responses).passed


# ----------------------------------------------------------------- verdict rejimi
COVERED = {
    "term": {
        "type": "quantity",
        "unit": "month",
        "near": ["warrant*"],
        "not_near": ["superseded", "add*", "extend*"],
    }
}


def test_verdict_mode_is_the_default_when_declared(make_case, make_response):
    case = make_case("consistency_at_k", {"verdict": COVERED})
    result = _grade(case, [make_response(text="A 24-month warranty applies.")] * 2)
    assert result.evidence["mode"] == "verdict"
    assert result.passed


def test_verdict_mode_requires_a_declaration(make_case, make_response):
    with pytest.raises(ValueError, match="verdict"):
        _grade(
            make_case("consistency_at_k", {"mode": "verdict"}),
            [make_response(text=STABLE)] * 2,
        )


def test_verdict_rejects_unknown_slot_type(make_case, make_response):
    with pytest.raises(ValueError, match="naməlum type"):
        _grade(
            make_case("consistency_at_k", {"verdict": {"x": {"type": "vibes"}}}),
            [make_response(text=STABLE)] * 2,
        )


def test_verdict_ignores_quantities_outside_the_declared_context(make_case, make_response):
    """Eyni qərar, fərqli əlavə detal — qərar sahəsi dəyişmirsə uyğunluq 1.0."""
    responses = [
        make_response(text="It has a 24-month warranty. Aurora Plus adds 6 months."),
        make_response(text="It has a 24-month warranty."),
    ]
    result = _grade(make_case("consistency_at_k", {"verdict": COVERED}), responses)
    assert result.passed
    assert result.evidence["majority_signature"] == [["term", ["24 month"]]]


def test_verdict_catches_a_genuine_decision_difference(make_case, make_response):
    """BİLƏRƏKDƏN SINAN: eyni sual, fərqli müddət → aşağı bal."""
    responses = [
        make_response(text="It has a 24-month warranty."),
        make_response(text="It has an 18-month warranty."),
    ]
    result = _grade(make_case("consistency_at_k", {"verdict": COVERED}), responses)
    assert not result.passed
    assert result.score == 0.5
    assert result.evidence["n_variants"] == 2


def test_label_slot_tracks_which_rule_was_cited(make_case, make_response):
    verdict = {
        "rule": {
            "type": "label",
            "labels": {"standard": ["standard policy"], "exception": ["exception clause"]},
        }
    }
    same = [make_response(text="Per the standard policy, yes.")] * 2
    differs = [
        make_response(text="Per the standard policy, yes."),
        make_response(text="Per the exception clause, yes."),
    ]
    assert _grade(make_case("consistency_at_k", {"verdict": verdict}), same).passed
    assert not _grade(make_case("consistency_at_k", {"verdict": verdict}), differs).passed


def test_verdict_skips_when_no_answer_states_the_decision(make_case, make_response):
    """ƏN VACİB MÜHAFİZƏ: "hamı susur" = "hamı razıdır" DEYİL.

    Slot heç bir cavabda oxunmursa grader 1.0 vermir — qərar verə bilmədiyini deyir.
    Bu olmasaydı, səhv slot spesifikasiyası bütün case-ləri yalançı yaşıla boyayardı.
    """
    responses = [make_response(text="Let me check that for you.")] * 3
    result = _grade(make_case("consistency_at_k", {"verdict": COVERED}), responses)
    assert result.skipped
    assert not result.passed
    assert "term" in result.reason


def test_verdict_partial_absence_is_a_real_disagreement(make_case, make_response):
    """Bir cavab qərarı deyir, digəri demir — bu SABİTSİZLİKDİR, susmaq deyil."""
    responses = [
        make_response(text="It has a 24-month warranty."),
        make_response(text="Let me check that for you."),
    ]
    result = _grade(make_case("consistency_at_k", {"verdict": COVERED}), responses)
    assert not result.passed
    assert not result.skipped
    assert result.evidence["unreadable_slots"]["term"] == [1]


def test_surface_metrics_are_reported_but_do_not_drive_the_score(make_case, make_response):
    """Səth oxşarlığı ikinci dərəcəli metrikdir — evidence-də var, balda yox."""
    responses = [
        make_response(text="It has a 24-month warranty. Aurora Plus adds 6 months."),
        make_response(text="A warranty of 24 months applies here."),
    ]
    result = _grade(make_case("consistency_at_k", {"verdict": COVERED}), responses)
    assert result.score == 1.0, "qərar eynidir — bal verdict-dən gəlir"
    assert result.evidence["surface"]["normalized_agreement"] == 0.5
    assert result.evidence["surface"]["numbers_agreement"] == 0.5


# ------------------------------------------------- REAL pilot qaçışı (fiksasiya)
def _pilot_responses(make_response):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data, [make_response(text=r["text"]) for r in data["responses"]]


def _pilot_case() -> Case:
    """Case DATASET-dən oxunur — sınaqda sübut olunan konfiq gerçəkdə qaçandır."""
    for line in PILOT_DATASET.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            return Case.from_dict(json.loads(line))
    raise AssertionError(f"{PILOT_DATASET} boşdur")


def test_pilot_fixture_is_the_real_run(make_response):
    data, responses = _pilot_responses(make_response)
    assert len(responses) == 3
    assert data["_provenance"]["run_id"] == "VSm2VX7XQhbAjVDkYpZPUF"
    assert data["_scores_before_fix"]["key_facts"] == pytest.approx(2 / 3)


def test_pilot_three_answers_now_score_a_perfect_one(make_response):
    """SÜBUT: üç REAL cavab eyni qərarı verdi → 1.0.

    Əvvəl: key_facts 0.67, numbers 0.33 — hər ikisi səth formasına görə.
    """
    _, responses = _pilot_responses(make_response)
    result = _grade(_pilot_case(), responses)
    assert result.passed
    assert result.score == 1.0
    assert result.evidence["majority_signature"] == [
        ["rule", ["aurora_brand", "superseded_18m"]],
        ["term", ["24 month"]],
    ]


def test_pilot_answers_under_canonical_key_facts(make_response):
    """Eyni fiksasiya, köhnə rejim + normallaşdırma: 0.67 → 1.0."""
    _, responses = _pilot_responses(make_response)
    case = Case(
        id="pilot-c1-t07-consistency",
        input="x",
        grader="consistency_at_k",
        expect={"mode": "key_facts", "key_facts": ["24 month", "18 month"]},
    )
    assert _grade(case, responses).score == 1.0


def test_pilot_grader_still_fails_on_a_real_term_change(make_response):
    """BİLƏRƏKDƏN SINAN, eyni real datada: bir cavab 18 ay desə, bal düşməlidir.

    Grader "hər şey keçsin" deyə boşaldılmayıb — dəyişiklik REAL cavabın
    yalnız qərar rəqəmindədir, qalan hər şey toxunulmazdır.
    """
    data, _ = _pilot_responses(make_response)
    texts = [r["text"] for r in data["responses"]]
    mutated = texts[2].replace("**24-month**", "**18-month**")
    assert mutated != texts[2], "mutasiya tətbiq olunmadı — test mənasız yaşıl olardı"

    responses = [
        _make_resp(texts[0]),
        _make_resp(texts[1]),
        _make_resp(mutated),
    ]
    result = _grade(_pilot_case(), responses)
    assert not result.passed
    assert result.score == pytest.approx(2 / 3)
    assert result.evidence["n_variants"] == 2
    assert ["term", ["18 month"]] in result.evidence["signatures"][2]


def _make_resp(text: str):
    from agentproof.types import AgentResponse

    return AgentResponse(text=text)


# ===========================================================================
# AP-006 — `mode=verdict` CANLI qaçışı (2026-08-27) və A-26 reqressiyası
# ===========================================================================
# Köhnə 0.67 rəqəmi `mode=key_facts`-dan gəlirdi və case artıq `verdict`-ə
# keçirilmişdi, amma REAL hədəfə qarşı yenidən qaçırılmamışdı. AP-006 onu
# qaçırdı — və qaçış DƏRHAL yeni bir grader qüsuru tapdı (A-26): `rule`
# slotunun cue siyahısı 2026-08-26 pilotunun SÖZLƏRİ üzərində qurulmuşdu.
#
# Bu bloku iki şey qoruyur:
#   (a) düzəlişdən ƏVVƏLKİ qaçışın cavabları indi 1.00 verir (əhatə bərpa
#       olundu) — amma yalnız `rule` slotu dəyişdi, `term` slotu toxunulmadı;
#   (b) bilərəkdən SINAN mutasiya: bir cavabda müddət 18 aya dəyişsə, bal
#       düşməlidir — yəni siyahının genişlənməsi grader-i kor etmədi.
AP006_FIXTURE = Path(__file__).parent / "fixtures" / "ap006_t07_consistency_verdict.json"


def _ap006(run: str, make_response):
    data = json.loads(AP006_FIXTURE.read_text(encoding="utf-8"))
    return data, [make_response(text=r["text"]) for r in data["runs"][run]["responses"]]


def test_ap006_fixture_is_the_real_live_run(make_response):
    data, responses = _ap006("run1", make_response)
    assert len(responses) == 3
    assert data["runs"]["run1"]["run_id"] == "AbmeRfQfdgNLf8jGA7SwJz"
    assert data["runs"]["run2"]["run_id"] == "kad8MmLsEqJxRN8i72392X"
    assert data["_scores"]["run1_declared_spec"] == pytest.approx(2 / 3)


@pytest.mark.parametrize("run", ["run1", "run2"])
def test_ap006_live_answers_are_verdict_stable(run, make_response):
    """SÜBUT (A-26 düzəlişindən sonra): hər iki canlı qaçışda 3/3 eyni qərar."""
    _, responses = _ap006(run, make_response)
    result = _grade(_pilot_case(), responses)
    assert result.passed
    assert result.score == 1.0
    assert result.evidence["majority_signature"] == [
        ["rule", ["aurora_brand", "superseded_18m"]],
        ["term", ["24 month"]],
    ]


def test_ap006_regression_rule_slot_accepts_version_wording(make_response):
    """A-26-nın DƏQİQ halı: «the 2025 v3.0 changes» = «superseded» ilə eyni qayda.

    run1-in 2-ci cavabı `superseded` sözünü ÜMUMİYYƏTLƏ işlətmir. Köhnə cue
    siyahısı ona görə `rule` slotunu yarımçıq oxuyurdu və 0.67 verirdi.
    """
    data, _ = _ap006("run1", make_response)
    second = data["runs"]["run1"]["responses"][1]["text"]
    assert "superseded" not in second.lower(), "fiksasiya dəyişib — test mənasız yaşıl olardı"
    assert "v3.0" in second.lower()
    result = _grade(_pilot_case(), [make_response(text=second)] * 2)
    assert result.evidence["majority_signature"] == [
        ["rule", ["aurora_brand", "superseded_18m"]],
        ["term", ["24 month"]],
    ]


def test_ap006_grader_still_fails_on_a_real_term_change(make_response):
    """BİLƏRƏKDƏN SINAN: genişlənmiş cue siyahısı `term` slotunu kor etmədi."""
    data, _ = _ap006("run2", make_response)
    texts = [r["text"] for r in data["runs"]["run2"]["responses"]]
    mutated = texts[0].replace("**24-month warranty**", "**18-month warranty**")
    assert mutated != texts[0], "mutasiya tətbiq olunmadı — test mənasız yaşıl olardı"
    result = _grade(
        _pilot_case(),
        [make_response(text=texts[1]), make_response(text=texts[2]), make_response(text=mutated)],
    )
    assert not result.passed
    assert result.score == pytest.approx(2 / 3)


def test_ap006_surface_metrics_are_reported_but_never_the_score(make_response):
    """Qərar: BAL verdict-dən gəlir, `numbers`/`normalized` GÖSTƏRİCİ qalır.

    run2-də səth metrikləri 0.33-dür (üçüncü cavab əlavə rəqəmlər saxlayır),
    verdict isə 1.00. Əgər səth rəqəmi hesabata sabitlik iddiası kimi düşsəydi,
    biz agenti qeyri-sabit elan edərdik — halbuki hər üç cavab eyni qərarı verir.
    """
    _, responses = _ap006("run2", make_response)
    result = _grade(_pilot_case(), responses)
    surface = result.evidence["surface"]
    assert result.score == 1.0
    assert surface["numbers_agreement"] < result.score
    assert surface["normalized_agreement"] < result.score

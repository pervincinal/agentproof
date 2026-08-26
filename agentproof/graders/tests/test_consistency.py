"""consistency_at_k (aqreqat grader)"""

from __future__ import annotations

import pytest

from agentproof.graders import registry

STABLE = "Qaytarma pəncərəsi 30 gündür, restocking haqqı 15%-dir."
STABLE_REWORDED = "Restocking haqqı 15%, qaytarma pəncərəsi isə 30 gündür."
DRIFTED = "Qaytarma pəncərəsi 45 gündür, restocking haqqı 20%-dir."


def _grade(case, responses):
    return registry.get("consistency_at_k").grade_many(case, responses)


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

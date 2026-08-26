"""contains_all · contains_none · regex_match"""

from __future__ import annotations

import pytest

from agentproof.graders import registry

ANSWER = "Qaytarma pəncərəsi 30 gündür, açılmış məhsullarda 15% restocking haqqı tutulur."


# ------------------------------------------------------------ contains_all
def test_contains_all_passes(make_case, make_response):
    result = registry.get("contains_all").grade(
        make_case("contains_all", {"all": ["30", "15%", "restocking"]}),
        make_response(text=ANSWER),
    )
    assert result.passed
    assert result.score == 1.0
    assert result.evidence["missing"] == []


def test_contains_all_fails_on_missing_phrase(make_case, make_response):
    result = registry.get("contains_all").grade(
        make_case("contains_all", {"all": ["30", "20%"]}),
        make_response(text=ANSWER),
    )
    assert not result.passed
    assert result.evidence["missing"] == ["20%"]
    assert "20%" in result.reason  # sınan case-in səbəbi boş qalmır


def test_contains_all_is_case_insensitive_by_default(make_case, make_response):
    assert registry.get("contains_all").grade(
        make_case("contains_all", {"all": ["RESTOCKING"]}), make_response(text=ANSWER)
    ).passed
    assert not registry.get("contains_all").grade(
        make_case("contains_all", {"all": ["RESTOCKING"], "case_sensitive": True}),
        make_response(text=ANSWER),
    ).passed


def test_contains_all_raises_when_dataset_lacks_expect(make_case, make_response):
    with pytest.raises(ValueError, match="expect.all"):
        registry.get("contains_all").grade(
            make_case("contains_all", {}), make_response(text=ANSWER)
        )


# ----------------------------------------------------------- contains_none
def test_contains_none_passes(make_case, make_response):
    result = registry.get("contains_none").grade(
        make_case("contains_none", {"none": ["$49", "hədiyyə kartı"]}),
        make_response(text=ANSWER),
    )
    assert result.passed
    assert result.evidence["hits"] == []


def test_contains_none_fails_when_forbidden_phrase_present(make_case, make_response):
    result = registry.get("contains_none").grade(
        make_case("contains_none", {"none": ["15%"]}), make_response(text=ANSWER)
    )
    assert not result.passed
    assert result.evidence["hits"] == ["15%"]


# ------------------------------------------------------------ regex_match
def test_regex_match_passes(make_case, make_response):
    result = registry.get("regex_match").grade(
        make_case("regex_match", {"pattern": r"\d+%\s+restocking"}), make_response(text=ANSWER)
    )
    assert result.passed
    assert result.evidence["match"] == "15% restocking"


def test_regex_match_fails(make_case, make_response):
    result = registry.get("regex_match").grade(
        make_case("regex_match", {"pattern": r"\d+ illik zəmanət"}), make_response(text=ANSWER)
    )
    assert not result.passed
    assert result.reason


def test_regex_match_inverted(make_case, make_response):
    """must_not_match=True: pattern TAPILMAMALIDIR."""
    assert registry.get("regex_match").grade(
        make_case("regex_match", {"pattern": r"\d+ illik", "must_not_match": True}),
        make_response(text=ANSWER),
    ).passed
    assert not registry.get("regex_match").grade(
        make_case("regex_match", {"pattern": r"\d+%", "must_not_match": True}),
        make_response(text=ANSWER),
    ).passed

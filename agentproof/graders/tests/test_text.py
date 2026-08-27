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


# --- contains_all: ÇILPAQ RƏQƏM iynələri (docs/GRADER-AUDIT.md#A-08) --------
# Tamamilə rəqəm olan iynə alt-sətir kimi YOX, müstəqil ədəd tokeni kimi
# axtarılır. Əks halda `"3"` iynəsi `2026-08-13`-ün içində tapılır və cavabda
# ədəd ümumiyyətlə olmasa belə case KEÇİR — yalançı YAŞIL.
EVASIVE = ("Delivery was attempted on 2026-08-13 for order ORD-10003. "
           "The policy does not state how many attempts are made.")
CONCRETE = "The courier makes 3 delivery attempts before returning to the depot."


def test_contains_all_numeric_needle_matches_real_quantity(make_case, make_response):
    assert registry.get("contains_all").grade(
        make_case("contains_all", {"all": ["3"]}), make_response(text=CONCRETE)
    ).passed


def test_contains_all_numeric_needle_does_not_match_inside_a_date(make_case, make_response):
    """A-08 REQRESSİYA: düzəlişdən əvvəl bu cavab KEÇİRDİ."""
    result = registry.get("contains_all").grade(
        make_case("contains_all", {"all": ["3"]}), make_response(text=EVASIVE)
    )
    assert not result.passed
    assert result.evidence["missing"] == ["3"]


@pytest.mark.parametrize("text", [
    "Order ORD-10014 shipped today.",          # identifikator
    "The parcel was delivered on 2026-08-14.",  # tarix
    "The refund is 164.00 AZN.",                # daha böyük ədədin içi
    "There are 114 days in the promotion.",     # daha böyük ədəd
])
def test_contains_all_numeric_needle_ignores_ids_dates_and_larger_numbers(
    make_case, make_response, text
):
    assert not registry.get("contains_all").grade(
        make_case("contains_all", {"all": ["14"]}), make_response(text=text)
    ).passed


def test_contains_all_numeric_needle_accepts_any_unit(make_case, make_response):
    """İynə vahid tələb etmir — ədədin FAKTİKİ deyildiyini tələb edir."""
    for text in ["within 14 calendar days", "14 gün ərzində", "a 14% fee", "the limit is 14"]:
        assert registry.get("contains_all").grade(
            make_case("contains_all", {"all": ["14"]}), make_response(text=text)
        ).passed, text


def test_contains_all_decimal_needle_is_canonicalised(make_case, make_response):
    g = registry.get("contains_all")
    assert g.grade(make_case("contains_all", {"all": ["149.99"]}),
                   make_response(text="The threshold is 149,99 AZN.")).passed
    assert not g.grade(make_case("contains_all", {"all": ["149.99"]}),
                       make_response(text="The threshold is 149 AZN.")).passed


def test_contains_all_reports_which_needles_were_numeric(make_case, make_response):
    result = registry.get("contains_all").grade(
        make_case("contains_all", {"all": ["7", "14", "warranty"]}),
        make_response(text="Report within 7 days; return within 14 days; warranty applies."),
    )
    assert result.passed
    assert result.evidence["numeric_needles"] == ["7", "14"]


# --- GERİYƏ UYĞUNLUQ: rəqəm olmayan iynələrin davranışı DƏYİŞMİR ------------
@pytest.mark.parametrize("needle,text,expected", [
    ("14 calendar days", "Report within 14 calendar days of delivery.", True),
    ("14 calendar days", "Report within 14 days of delivery.", False),
    ("невозможен", "К сожалению, возврат уже невозможен.", True),
    ("невозможен", "Возврат ещё возможен.", False),
    ("20%", "A 20% restocking fee applies.", True),
    ("order date", "The window runs from the order date.", True),
    ("24-month", "It has a 24-month warranty.", True),
    # alt-sətir davranışı qəsdən saxlanılır: mətn iynəsi söz ortasında da tapılır
    ("warrant", "The warranty is still valid.", True),
])
def test_contains_all_text_needles_behave_exactly_as_before(
    make_case, make_response, needle, text, expected
):
    assert registry.get("contains_all").grade(
        make_case("contains_all", {"all": [needle]}), make_response(text=text)
    ).passed is expected


def test_contains_all_text_needle_is_not_routed_through_numeric_path(
    make_case, make_response
):
    result = registry.get("contains_all").grade(
        make_case("contains_all", {"all": ["14 calendar days", "warranty"]}),
        make_response(text="Return within 14 calendar days; the warranty still applies."),
    )
    assert result.passed
    assert result.evidence["numeric_needles"] == []


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

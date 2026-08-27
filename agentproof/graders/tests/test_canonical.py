"""Kəmiyyət normallaşdırma qatı (`graders/canonical.py`).

Bu qat `consistency_at_k`-nın altındadır, amma AYRICA test olunur — çünki
pilotdakı sınıq məhz burada idi: `24 months` ilə `24-month` fərqli sayılırdı,
tarixlər isə "fakt" kimi toplanırdı.

Hər davranışın bilərəkdən KEÇƏN və bilərəkdən SINAN nümunəsi var.
"""

from __future__ import annotations

import pytest

from agentproof.graders.canonical import (
    DateValue,
    Quantity,
    analyze,
    canonical_text,
    contains_quantity,
    cue_matches,
    extract_dates,
    contains_number,
    extract_quantities,
    numeric_spec,
    parse_quantity,
)


def _q(text: str) -> set[str]:
    return {q.key for q in extract_quantities(text)}


def _d(text: str) -> set[str]:
    return {d.iso for d in extract_dates(text)}


# ------------------------------------------------------- müddət kanonikləşməsi
@pytest.mark.parametrize(
    "text",
    [
        "24 months",
        "24 month",
        "24-month",
        "24-months",
        "24 mo",
        "24mo",
        "24 mos",
        "twenty-four months",
        "**24-month** warranty",
        "24 aylıq",
    ],
)
def test_duration_surface_forms_collapse_to_one_quantity(text):
    """Pilotun əsas sınığı: `24 months` və `24-month` EYNİ fakt olmalıdır."""
    assert _q(text) == {"24 month"}


def test_different_durations_do_not_collapse():
    """Bilərəkdən SINAN: 24 ay ilə 18 ay eyni sayılmamalıdır."""
    assert _q("24 months") != _q("18 months")


def test_units_are_not_interchangeable():
    """`24 month` ilə `24 day` fərqli faktdır — vahid imzanın bir hissəsidir."""
    assert _q("24 months") != _q("24 days")


@pytest.mark.parametrize(
    "text",
    ["6 more months", "6 additional months", "6 extra months", "six full months", "6 əlavə ay"],
)
def test_modifier_between_number_and_unit(text):
    """`6 more months` ilə `6 months` eyni faktdır — `more` ifadə seçimidir."""
    assert _q(text) == {"6 month"}


def test_modifier_alone_does_not_invent_a_unit():
    """Bilərəkdən SINAN: vahid yoxdursa müəyyənləşdirici vahid uydurmamalıdır."""
    assert _q("6 more") == {"6 count"}


def test_business_day_is_a_distinct_unit():
    """`5 iş günü` ≠ `5 gün` — qaytarma siyasətlərində bu fərq real."""
    assert _q("5 business days") == {"5 business_day"}
    assert _q("5 business days") != _q("5 days")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("30 gün", "30 day"),
        ("30 gündür", "30 day"),
        ("30 günə", "30 day"),
        ("15 faizdir", "15 percent"),
        ("2 illik", "2 year"),
        ("3 həftədən", "3 week"),
    ],
)
def test_azerbaijani_units_with_agglutinative_suffixes(text, expected):
    assert _q(text) == {expected}


@pytest.mark.parametrize("text", ["2 ayrı paket", "3 ilk addım"])
def test_azerbaijani_suffix_list_is_closed(text):
    """Bilərəkdən SINAN: `ayrı` ay-a, `ilk` il-ə çevrilməməlidir."""
    assert all(q.unit == "count" for q in extract_quantities(text))


# --------------------------------------------------------------- faiz/valyuta
@pytest.mark.parametrize("text", ["15%", "15 %", "15 percent", "15 pct", "15.0%", "15 faiz"])
def test_percent_forms(text):
    assert _q(text) == {"15 percent"}


def test_percent_value_difference_survives():
    assert _q("15%") != _q("20%")


@pytest.mark.parametrize("text", ["$1,200", "$1200", "1200 USD", "USD 1200", "1,200.00 dollars"])
def test_currency_forms(text):
    assert _q(text) == {"1200 usd"}


def test_currency_kind_is_part_of_the_fact():
    """1200 USD ilə 1200 AZN eyni fakt deyil."""
    assert _q("$1200") != _q("1200 AZN")
    assert _q("1200₼") == {"1200 azn"}


def test_decimal_comma_versus_thousands_separator():
    assert _q("15,5%") == {"15.5 percent"}
    assert _q("$1,500") == {"1500 usd"}


# ------------------------------------------------------------------ tarixlər
@pytest.mark.parametrize(
    "text,iso",
    [
        ("2026-09-01", "2026-09-01"),
        ("2026/09/01", "2026-09-01"),
        ("09/01/2026", "2026-09-01"),
        ("01.09.2026", "2026-09-01"),
        ("September 1, 2024", "2024-09-01"),
        ("1 September 2024", "2024-09-01"),
        ("September 2024", "2024-09"),
        ("March 2027", "2027-03"),
        ("sentyabr 2024", "2024-09"),
    ],
)
def test_date_forms_are_recognised(text, iso):
    assert _d(text) == {iso}


@pytest.mark.parametrize("text", ["2026-09-01", "September 2024", "in 2024", "March 2027"])
def test_dates_are_not_quantities(text):
    """PİLOTUN İKİNCİ SINIĞI: tarix qərar rəqəmi deyil, ona görə kəmiyyət sayılmır."""
    assert _q(text) == set()


def test_ambiguous_slash_date_falls_back_to_day_first():
    """13/01/2026 ABŞ formatı ola bilməz — 13-cü ay yoxdur."""
    assert _d("13/01/2026") == {"2026-01-13"}


def test_identifier_is_not_a_number():
    """`ORD-10046` sifariş nömrəsidir, siyasət rəqəmi deyil."""
    assert _q("order ORD-10046 was delivered") == set()


def test_a_real_policy_number_next_to_an_identifier_still_counts():
    """Bilərəkdən KEÇƏN qarşılığı: identifikator filtri əsl rəqəmi udmamalıdır."""
    assert _q("order ORD-10046 carries a 24-month warranty") == {"24 month"}


# -------------------------------------------------------------- spesifikasiya
def test_parse_quantity_accepts_pure_spec():
    assert parse_quantity("24 month") == Quantity("24", "month")
    assert parse_quantity("15%") == Quantity("15", "percent")


def test_parse_quantity_rejects_mixed_spec():
    """Təmiz kəmiyyət deyilsə None — çağıran mətn axtarışına qayıtsın."""
    assert parse_quantity("24 months of warranty") is None
    assert parse_quantity("Aurora-brand") is None


def test_contains_quantity_matches_across_surface_forms():
    text = "the item carries a **24-month** Aurora warranty"
    assert contains_quantity(text, Quantity("24", "month"))
    assert not contains_quantity(text, Quantity("18", "month"))


# ----------------------------------------------------------------- bənd/işarə
def test_clauses_split_on_dash_and_parentheses_not_on_comma():
    a = analyze("It carries a 24-month warranty — the 18-month rule (superseded) does not apply.")
    clauses = [a.span(lo, hi) for lo, hi in a.clauses]
    assert any("24-month warranty" in c for c in clauses)
    assert all("24-month" not in c or "18-month" not in c for c in clauses)


def test_clause_split_does_not_break_decimals_or_iso_dates():
    """Nöqtə bənd sərhədidir — amma `15.5%` və `2026-09-01` tokenin İÇİNDƏDİR."""
    a = analyze("The fee is 15.5% and coverage ends 2026-09-01 today.")
    assert {q.key for q in a.quantities} == {"15.5 percent"}
    assert len(a.clauses) == 1


def test_cue_exact_versus_prefix():
    assert cue_matches("the warranty applies", "warranty")
    assert not cue_matches("the warranties apply", "warranty")
    assert cue_matches("the warranties apply", "warrant*")
    assert not cue_matches("we cover it", "warrant*")


def test_cue_does_not_match_inside_a_word():
    """`plus` sözü `surplus`-un içində tapılmamalıdır."""
    assert not cue_matches("a surplus of stock", "plus")
    assert cue_matches("aurora plus membership", "plus")


def test_canonical_text_keeps_newlines_as_clause_boundaries():
    ct = canonical_text("A 24-month term\n\nA 18-month term")
    assert ct.count("\n") == 1
    assert len(analyze("A 24-month term\nA 18-month term").clauses) == 2


def test_dataclasses_are_hashable_for_signatures():
    """İmzalar `Counter`-ə düşür — dəyərlər hashable olmalıdır."""
    assert len({Quantity("24", "month"), Quantity("24", "month")}) == 1
    assert len({DateValue("2026-09-01"), DateValue("2026-09-01")}) == 1


# ------------------------------------------------- numeric_spec / contains_number
# docs/GRADER-AUDIT.md#A-08 — `contains_all` çılpaq rəqəm iynələri.
@pytest.mark.parametrize("spec,expected", [
    ("14", "14"),
    ("3", "3"),
    ("149.99", "149.99"),
    ("149,99", "149.99"),   # onluq vergül
    ("1,200", "1200"),      # min ayırıcısı
    ("  20  ", "20"),
])
def test_numeric_spec_canonicalises_bare_numbers(spec, expected):
    assert numeric_spec(spec) == expected


@pytest.mark.parametrize("spec", [
    "14 calendar days", "24-month", "20%", "невозможен", "order date",
    "warranty", "ORD-10015", "", "14 gün",
])
def test_numeric_spec_returns_none_for_text_needles(spec):
    """Rəqəm OLMAYAN iynə köhnə alt-sətir yolunda qalmalıdır (geriyə uyğunluq)."""
    assert numeric_spec(spec) is None


@pytest.mark.parametrize("text", [
    "Report damage within 14 calendar days.",
    "You have 14 days left.",
    "Zədə barədə 14 gün ərzində bildirin.",
    "A 14% restocking fee applies.",
    "The deadline is 14.",
    "Fourteen is written as 14 in the policy.",
])
def test_contains_number_finds_independent_quantity(text):
    assert contains_number(text, "14")


@pytest.mark.parametrize("text", [
    "The parcel was delivered on 2026-08-14.",      # ISO tarix
    "Delivered 14/09/2026 to the depot.",           # gün/ay/il
    "Delivered on 14 September 2026.",              # adlı tarix
    "Order ORD-10014 is on its way.",               # identifikator
    "The SKU is AG-PRT-1140.",                      # identifikator
    "The refund is 164.00 AZN.",                    # daha böyük ədədin içi
    "There are 114 days in the promotion.",         # daha böyük ədəd
    "The fee is 1.14 AZN.",                         # onluq hissə
])
def test_contains_number_does_not_leak_out_of_dates_ids_or_larger_numbers(text):
    """A-08-in mahiyyəti: rəqəm öz token sərhədindən KƏNARA çıxmır."""
    assert not contains_number(text, "14")


def test_contains_number_distinguishes_zero_and_empty_text():
    assert contains_number("The fee is 0 AZN for Aurora Plus members.", "0")
    assert not contains_number("", "14")

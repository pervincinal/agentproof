"""A-08 — `contains_all` çılpaq rəqəm iynələri (docs/GRADER-AUDIT.md#A-08).

Tapılmış səhv
-------------
`ContainsAll` alt-sətir axtarışı idi. `base-mft-delivery-attempts` case-inin
iynəsi `"3"`-dür; tamamilə qaçamaq cavab —

    «Attempted on 2026-08-13; the exact number of attempts is not stated.»

— cəhd sayını HEÇ demir, amma `"3"` tarixin içində (`...-1<3>`) tapılır və case
**KEÇİRDİ**. Bu, yalançı YAŞILDIR: yalançı qırmızıdan pisdir, çünki real
uğursuzluğu gizlədir və hesabatda heç bir yerdə görünmür.

Düzəliş **grader səviyyəsindədir**, case-bəcase yamaq deyil: iynə tamamilə
rəqəmdirsə, `canonical.contains_number()` onu MÜSTƏQİL ədəd tokeni kimi
axtarır. `canonical.analyze()` tarixi (`DateValue`), identifikatoru
(`ORD-10015`) və çoxrəqəmli ədədi (`164.00`) artıq ayrı token kimi tanıyır —
təkər yenidən icad edilmir.

Bu fayl HƏR iynə üçün iki istiqaməti sübut edir: düzgün cavab KEÇİR, rəqəmin
yalnız tarix/ID içində göründüyü qaçamaq cavab SINIR.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agentproof.graders import registry
from agentproof.runner.task import load_cases
from agentproof.types import AgentResponse, Case

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals" / "datasets" / "full.jsonl"


@pytest.fixture(scope="module")
def cases() -> dict[str, Case]:
    return {c.id: c for c in load_cases(DATASET)}


# ---------------------------------------------------------------- inventar
def test_bare_number_needles_are_a_known_closed_set(cases: dict[str, Case]) -> None:
    """Yeni çılpaq rəqəm iynəsi əlavə olunsa, bu test onu görünən edir.

    Məqsəd qadağa deyil — indi grader onları düzgün işləyir. Məqsəd: siyahı
    audit sənədi ilə sinxron qalsın (A-08 bağlıdır, amma nəzarətsiz deyil).
    """
    found: dict[str, list[str]] = {}
    for cid, c in cases.items():
        if c.grader != "contains_all":
            continue
        bare = [str(n) for n in c.expect["all"]
                if re.fullmatch(r"\d+(?:[.,]\d+)?", str(n))]
        if bare:
            found[cid] = bare
    assert found == {
        "base-mft-restocking-fee-opened": ["15"],
        "base-mft-warranty-third-party": ["12"],
        "base-mft-delivery-attempts": ["3"],
        "g3-ord10026-two-tracks": ["7", "14"],
        "g3-ord10063-two-anchors": ["14"],
        "pw-11-en-damage_complaint-international-current-t5": ["14"],
    }, f"çılpaq rəqəm iynələri dəyişib: {json.dumps(found, indent=2)}"


# ------------------------------------------------- uçdan-uca iki istiqamət
# (case_id, DÜZGÜN cavab, QAÇAMAQ cavab)
# Qaçamaq cavabda iynənin rəqəmləri MÖVCUDDUR, amma yalnız tarixin / sifariş
# nömrəsinin / daha böyük ədədin İÇİNDƏ — yəni agent sualın cavabını vermir.
NUMERIC_PROBES: list[tuple[str, str, str]] = [
    ("base-mft-delivery-attempts",
     "The courier makes 3 delivery attempts before the parcel is returned to the depot.",
     "Delivery was attempted on 2026-08-13 for order ORD-10003. The policy does not "
     "state how many attempts are made."),
    ("base-mft-restocking-fee-opened",
     "An opened but resalable item carries a 15% restocking fee.",
     "For order ORD-10015 delivered on 2026-08-15 a restocking fee may apply; the exact "
     "percentage is not specified in the knowledge base."),
    ("base-mft-warranty-third-party",
     "A third-party brand product bought today carries a 12-month standard warranty.",
     "The item was delivered on 2026-08-12 under order ORD-10012. I could not find the "
     "warranty length for third-party brands."),
    ("g3-ord10026-two-tracks",
     "The transit damage reporting deadline is 7 calendar days, so at 8 days it has "
     "passed. You can still return the item within the 14 calendar day return window, "
     "and a manufacturer warranty claim remains open.",
     "Order ORD-10026 was delivered on 2026-08-14 and reported on 2026-08-17. I cannot "
     "tell you the reporting deadline or the return window length."),
    ("g3-ord10063-two-anchors",
     "The price match claim is anchored to the order date, not delivery: you have "
     "14 calendar days from the order date, so the claim is closed.",
     "Order ORD-10063 was placed on 2026-08-14 and delivered on 2026-08-18. The order "
     "date is what matters here, but I cannot state the claim window."),
    ("pw-11-en-damage_complaint-international-current-t5",
     "Transit damage must be reported within 14 calendar days of delivery; at 22 days "
     "that deadline has passed.",
     "Order ORD-10014 was delivered on 2026-08-14. I am not able to state the damage "
     "reporting deadline."),
]


@pytest.mark.parametrize("cid,good,evasive", NUMERIC_PROBES, ids=[p[0] for p in NUMERIC_PROBES])
def test_numeric_needle_grades_both_directions(
    cases: dict[str, Case], cid: str, good: str, evasive: str
) -> None:
    case = cases[cid]
    grader = registry.get(case.grader)
    ok = grader.grade(case, AgentResponse(text=good))
    bad = grader.grade(case, AgentResponse(text=evasive))
    assert ok.passed, f"{cid}: DÜZGÜN cavab sındı (yalançı müsbət) — {ok.reason}"
    assert not bad.passed, (
        f"{cid}: QAÇAMAQ cavab keçdi — YALANÇI YAŞIL, A-08 hələ açıqdır. {bad.reason}"
    )


def test_every_bare_number_case_has_a_probe(cases: dict[str, Case]) -> None:
    """Audit sistematikdir: çılpaq rəqəm iynəsi olan HƏR case probe-lanır."""
    bare_cases = {cid for cid, c in cases.items()
                  if c.grader == "contains_all"
                  and any(re.fullmatch(r"\d+(?:[.,]\d+)?", str(n)) for n in c.expect["all"])}
    probed = {p[0] for p in NUMERIC_PROBES}
    assert bare_cases == probed, f"probe-lanmamış: {sorted(bare_cases - probed)}"


def test_evasive_answer_used_to_pass_before_the_fix(cases: dict[str, Case]) -> None:
    """REQRESSİYA: audit sənədində sitat gətirilən konkret yalançı yaşıl.

    Düzəlişdən əvvəl `"3"` iynəsi `2026-08-13`-ün içində tapılırdı və bu cavab
    `passed=True` verirdi.
    """
    case = cases["base-mft-delivery-attempts"]
    text = ("Sifariş 2026-08-13 tarixində çatdırılmağa cəhd edilib. "
            "Dəqiq say göstərilməyib.")
    result = registry.get(case.grader).grade(case, AgentResponse(text=text))
    assert not result.passed
    assert result.evidence["numeric_needles"] == ["3"]
    assert result.evidence["missing"] == ["3"]


def test_date_and_id_shaped_needles_stay_on_the_substring_path(
    cases: dict[str, Case]
) -> None:
    """Tarix/ID formalı iynə ÇILPAQ RƏQƏM deyil — köhnə yolda qalmalıdır.

    `"2026-03-01"` ədəd tokeni kimi axtarılsaydı heç vaxt tapılmazdı
    (`analyze()` onu `DateValue` sayır, kəmiyyət yox) — düzəliş yeni yalançı
    qırmızı yaratmamalıdır.
    """
    checks = [
        ("r6b-t07-ord10046-expiry-date",
         "The warranty on ORD-10046 ran to 2026-03-01.", True),
        ("r6b-t07-ord10046-expiry-date",
         "The warranty end date is not stated in the knowledge base.", False),
        ("t1-w05-ord10058-existing-rma",
         "An RMA already exists for this order: RMA-20260830-0001.", True),
        ("t1-w05-ord10058-existing-rma",
         "I opened a brand new return for you.", False),
    ]
    for cid, text, expected in checks:
        case = cases[cid]
        result = registry.get(case.grader).grade(case, AgentResponse(text=text))
        assert result.passed is expected, f"{cid}: {text!r} → {result.reason}"
        assert result.evidence["numeric_needles"] == [], (
            f"{cid}: iynə səhvən ədəd yoluna düşdü"
        )

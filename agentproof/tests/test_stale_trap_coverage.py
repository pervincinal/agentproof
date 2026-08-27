"""AP-015 — örtülməmiş 13 bayat tələ üçün əlavə edilən case-lərin auditi.

Niyə bu fayl var
----------------
`COVERAGE.md §9.1` açıq elan edirdi: 27 bayat tələdən yalnız 14-ünün ayrıca
case-i var. Yəni hesabatın ən önəmli rəqəmlərindən biri — **stale-answer
rate** — 14 tələ üzərində hesablanırdı, 27 üzərində yox. R6 bizim ən güclü
tapıntı blokumuzdur; onun bazası natamam qalsa, blokun bütün nəticəsi
şübhəlidir.

Yeni case əlavə etmək asandır; **onun nəyi ölçdüyünü sübut etmək** çətindir.
`docs/GRADER-AUDIT.md` A-01…A-23-ün hamısı eyni dərsdən doğur: assertion
sınandıqda səbəbin agentdə, yoxsa iynədə olduğunu bilmiriksə, tapıntı
etibarsızdır. Ona görə hər yeni case burada **İKİ İSTİQAMƏTDƏ** qaçırılır:

  (a) kanonik olaraq DÜZGÜN cavab dataset grader-ini KEÇMƏLİDİR
      → yalançı müsbət yoxdur;
  (b) bayat bəndə əsaslanan cavab SINMALIDIR
      → yalançı yaşıl yoxdur.

Üçüncü sətir (`DISTRACTOR`) daha incə haldır: agentin **düzgün qonşu faktı**
(başqa parametrin canlı dəyəri, eyni rəqəmlə) case-i sındırmamalıdır. A-07,
A-15, A-17 və A-23 məhz bu sinifdəndir — `30 gün` korpusda ALTI, `14 gün` BEŞ
canlı parametrdir.

Cavab mətnləri sintetikdir və bu, açıq bildirilir: bu case-lər hələ canlı
hədəfə qarşı qaçırılmayıb (`GRADER-AUDIT.md` "Məhdudiyyət" qeydi ilə eyni
formada). Canlı qaçışdan sonra real cavablar buraya köçürülməlidir.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentproof.graders import registry
from agentproof.runner.task import load_cases
from agentproof.types import AgentResponse, Case

DATASET = Path(__file__).resolve().parents[2] / "evals" / "datasets" / "full.jsonl"


@pytest.fixture(scope="module")
def cases() -> dict[str, Case]:
    return {c.id: c for c in load_cases(DATASET)}


# ---------------------------------------------------------------------------
# (case_id, KEÇMƏLİ cavablar, SINMALI cavablar)
#   * KEÇMƏLİ: kanonik cavab + mümkün olduqda distraktor saxlayan variant
#   * SINMALI: bayat bəndin dəyərini/verdiktini işlədən cavab
# ---------------------------------------------------------------------------
PROBES: list[tuple[str, list[str], list[str]]] = [
    # --- T-04: bayat «etiket həmişə pulsuz» ↔ cari 150.00 AZN həddi, 9.90 haqq
    ("r6a-t04-free-label-any-value",
     ["Because the merchandise value is 60.00 AZN, which is below the 150.00 AZN "
      "threshold, a 9.90 AZN return label fee applies.",
      "That order is under 150.00 AZN, so the return label costs 9.90 AZN."],
     ["Return labels are free on all orders, so there is nothing to pay.",
      "Good news — your return label is free regardless of the order value."]),

    # --- T-10: bayat COD limiti 300.00 ↔ cari 500.00
    ("r6a-t10-cod-400-azn",
     ["Yes — at 400.00 AZN you are within the 500.00 AZN cash-on-delivery limit, so "
      "COD is available for this order.",
      "You can pay cash on delivery; the limit is 500.00 AZN and a 3.00 AZN handling "
      "fee is added."],
     ["No, cash on delivery is only available for orders of 300.00 AZN or less, so it "
      "is not available for a 400.00 AZN basket.",
      "Unfortunately COD is not possible above the 300.00 AZN limit."]),

    # --- T-11: bayat taksit minimumu 150.00 ↔ cari 200.00
    ("r6a-t11-instalment-175-azn",
     ["No — instalments require a minimum order value of 200.00 AZN and your order is "
      "175.00 AZN, so it does not qualify.",
      "Your order falls just short of the 200.00 AZN instalment minimum."],
     ["Yes, 175.00 AZN is above the 150.00 AZN instalment minimum, so you can split it "
      "into 3 or 6 monthly payments.",
      "Sure — instalments are available from 150.00 AZN upwards."]),

    # --- T-12: bayat «bonus yoxdur» ↔ cari 5% bonus
    ("r6a-t12-store-credit-bonus",
     ["Yes — if you take the refund as store credit we add a 5% bonus on top of the "
      "refunded amount.",
      "Store credit is issued with an extra 5 percent bonus."],
     ["No, store credit is issued at face value — there is no bonus.",
      "Store credit carries no uplift; you receive exactly the refunded amount."]),

    # --- T-16: bayat 3 uğursuz cəhd ↔ cari 5
    ("r6a-t16-lockout-attempts",
     ["Your account is locked after 5 consecutive failed sign-in attempts, for 30 "
      "minutes.",
      # DISTRAKTOR: korpusda CANLI «3» iki yerdə var — kuryerin 3 çatdırılma
      # cəhdi və 3 təkrar ödəniş cəhdi. Onlar case-i sındırmamalıdır.
      "After 5 failed sign-in attempts the account locks. That is unrelated to the 3 "
      "delivery attempts a courier makes, or to the 3 recurring payment retries."],
     ["Your account is locked after 3 failed sign-in attempts.",
      "3 incorrect password attempts in a row will lock the account for 30 minutes."]),

    # --- T-17: bayat 90 gün ↔ cari 30 gün
    ("r6a-t17-erasure-completion",
     ["Erasure is completed within 30 calendar days after the grace period ends.",
      "Once the 14-day grace period has passed, deletion completes within 30 days."],
     ["Erasure is completed within 90 calendar days of the request.",
      "Silinmə sorğudan sonra 90 gün ərzində tamamlanır."]),

    # --- T-18: bayat 36 ay ↔ cari 24 ay
    ("r6a-t18-support-transcript-retention",
     ["Support transcripts are retained for 24 months and then deleted.",
      "Dəstək yazışmaları 24 ay saxlanılır."],
     ["Support transcripts are retained for 36 months.",
      "Мы храним переписку поддержки 36 месяцев."]),

    # --- T-19: bayat «30 gün» ↔ cari 72 saat (ən kəskin A-07 toqquşması)
    ("r6a-t19-data-export-time",
     ["Your data export is delivered within 72 hours of the request.",
      # DISTRAKTOR: eyni cavabda CANLI 30 gün var, amma BAŞQA parametrdir
      # (erasure completion / DPO cavab müddəti) — tutulmamalıdır.
      "The export itself is delivered within 72 hours. Account erasure is a separate "
      "process and completes within 30 calendar days.",
      "Exports take 72 hours; a formal DPO request is answered within 30 days."],
     ["Your data export will be delivered within 30 calendar days.",
      "We provide the copy of your data within 30 days of the request."]),

    # --- T-21: bayat 25% ↔ cari 30%
    ("r6a-t21-promotional-threshold",
     ["An item counts as promotional at a discount of 30% or more.",
      # DISTRAKTOR: 25.00 AZN korpusda CANLI iki dəyərdir (ağır yük əlavəsi,
      # diaqnostika haqqı) — faiz iynəsi onları tutmamalıdır.
      "The promotional threshold is 30%. Unrelated: the heavy-item surcharge is "
      "25.00 AZN and the diagnostic fee is 25.00 AZN."],
     ["An item counts as promotional at a discount of 25% or more.",
      "Promosyon həddi 25 faizdir."]),

    # --- T-23 (A): bayat 14 gün ↔ cari 21 gün (beynəlxalq)
    ("r6a-t23-intl-window-today",
     ["For an international order placed today you have 21 calendar days from delivery "
      "to return it.",
      # DISTRAKTOR: kontrastlı düzgün cavab — 14 gün DOMESTİK pəncərədir.
      "International returns run to 21 calendar days, not the 14-day domestic window.",
      "You get 21 calendar days. The standard domestic window is 14 calendar days and "
      "the price match window is also 14 days from the order date."],
     ["For an international order you have 14 calendar days to return the item.",
      "The international return window is 14 days from delivery."]),

    # --- T-24: bayat «DDP yoxdur, həmişə DDU» ↔ cari 1000.00 AZN həddi
    ("r6a-t24-ddp-threshold",
     ["At 1,200.00 AZN the order is above the 1000.00 AZN threshold, so it ships DDP "
      "and Aurora Goods pays the duties and taxes.",
      "Duties are prepaid on this shipment — we cover them (DDP)."],
     ["All international orders ship DDU, so you will pay any import duties on "
      "delivery.",
      "There is no DDP option; you will be responsible for the customs duties."]),

    # --- T-26: bayat «yalnız 3 və 6 ay» ↔ cari [3, 6, 12]
    ("r6a-t26-instalment-terms",
     ["We offer 3-, 6- and 12-month instalment plans.",
      "Plans available: 3, 6 or 12 months."],
     ["We offer 3- and 6-month instalment plans.",
      # DİQQƏT: burada `12` var, amma ZƏMANƏT kontekstindədir — taksit
      # planı kimi sayılmamalıdır, yəni case SINMALIDIR.
      "Instalments come in 3- and 6-month terms only. Separately, third-party brands "
      "carry a 12 month warranty."]),

    # --- T-27: bayat «güzəşt yoxdur» ↔ cari 14 gün
    ("r6a-t27-erasure-grace-period",
     ["Yes — there is a 14-day grace period during which you can cancel the erasure "
      "request.",
      "You have 14 calendar days to change your mind before deletion starts."],
     ["No — once submitted, an erasure request cannot be reversed; there is no grace "
      "period.",
      "Deletion starts immediately and cannot be stopped."]),

    # --- İSTİQAMƏT B: bayat bənd HƏLƏ DƏ QÜVVƏDƏDİR ------------------------
    # T-23-B: 2026-05-10-da verilmiş beynəlxalq sifariş → v1.5 → 14 gün.
    # «Həmişə ən yeni rəqəmi seç» strategiyası məhz burada sınır.
    ("r6b-t23-intl-order-placed-may-2026",
     ["That order was placed on 2026-05-10, while v1.5 was still in force, so the "
      "international return window for it was 14 calendar days.",
      "Because the order predates the 2026-07-01 change, you had 14 calendar days."],
     ["You had 21 calendar days to return it.",
      "The international return window is 21 calendar days, so that applied to your "
      "order as well."]),

    # T-13-B: `fee_actually_charged` → 39.00 AZN, cari 49.00 DEYİL.
    ("r6b-t13-plus-fee-refund-basis",
     ["Your refund is calculated pro-rata on the 39.00 AZN you were actually charged, "
      "not on the current fee.",
      "The basis is the fee you paid: 39.00 AZN."],
     ["Your refund is calculated on the current annual fee of 49.00 AZN.",
      "The membership fee is 49.00 AZN, and your refund is a pro-rata share of that."]),
]


def _grade(case: Case, text: str):
    return registry.get(case.grader).grade(case, AgentResponse(text=text))


@pytest.mark.parametrize(
    "case_id,text",
    [(cid, t) for cid, ok, _ in PROBES for t in ok],
    ids=[f"{cid}#ok{i}" for cid, ok, _ in PROBES for i in range(len(ok))],
)
def test_canonically_correct_answer_passes(cases: dict[str, Case], case_id: str, text: str):
    result = _grade(cases[case_id], text)
    assert result.passed, f"{case_id}: DÜZGÜN cavab sındı — {result.reason}"


@pytest.mark.parametrize(
    "case_id,text",
    [(cid, t) for cid, _, bad in PROBES for t in bad],
    ids=[f"{cid}#stale{i}" for cid, _, bad in PROBES for i in range(len(bad))],
)
def test_stale_clause_answer_fails(cases: dict[str, Case], case_id: str, text: str):
    result = _grade(cases[case_id], text)
    assert not result.passed, f"{case_id}: BAYAT cavab keçdi (yalançı YAŞIL) — {text!r}"


def test_every_new_ap015_case_has_a_two_way_probe(cases: dict[str, Case]) -> None:
    """Probe-suz yeni case qalmamalıdır — əks halda nəyi ölçdüyünü bilmirik."""
    probed = {cid for cid, _, _ in PROBES}
    ap015 = {
        c.id for c in cases.values()
        if "R6" in c.tags and any(
            t in c.tags for t in
            ("T-04", "T-10", "T-11", "T-12", "T-16", "T-17", "T-18", "T-19",
             "T-21", "T-23", "T-24", "T-26", "T-27")
        )
    } | {"r6b-t13-plus-fee-refund-basis"}
    assert ap015 <= probed, f"probe-u olmayan case(lər): {sorted(ap015 - probed)}"
    assert probed <= set(cases), f"mövcud olmayan case-ə probe: {sorted(probed - set(cases))}"

"""AZ / RU (və EN) grader pattern-lərinin MORFOLOJİ audit testi.

Niyə bu fayl var
----------------
`reports/smoke-full2/` qaçışında `l1-ru-ord10015-verdict` case-i "sındı"
göstərdi. Agent isə TAM DÜZGÜN cavab vermişdi:

    «К сожалению, возврат уже невозможен. — Товар доставлен 12.08.2026, прошло
     20 дней. — Стандартное окно возврата — 14 календарных дней...»

Səhv agentdə deyil, BİZDƏ idi: pattern `невозможн` axtarırdı, cavabda isə
`невозможен` vardı (rus dilində kişi cinsi qısa formada beglaya glasnaya —
düşən sait — yaranır, kök `невозможн`-a uyğun gəlmir).

L1 bloku ÇARPAZ-DİL DELTA-sını ölçür. Əgər AZ/RU pattern-i EN-dən daha dar
olsa, ölçdüyümüz delta agentin deqradasiyası yox, öz grader-imizin morfoloji
boşluğudur. Yalançı müsbət tapıntı buraxılmış tapıntıdan pisdir.

Test HƏR İKİ istiqaməti sübut edir:
  (a) düzgün RƏDD cavabı tutulmalıdır (morfoloji əhatə),
  (b) düzgün QƏBUL cavabı tutulmamalıdır (həddindən artıq genişlənmə yoxdur).

Sənədləşmə: `docs/GRADER-AUDIT.md`.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest

from agentproof.graders import registry
from agentproof.graders.canonical import contains_phrase
from agentproof.runner.task import load_cases
from agentproof.types import AgentResponse, Case

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "evals" / "datasets" / "build_full.py"
DATASET = ROOT / "evals" / "datasets" / "full.jsonl"


@pytest.fixture(scope="module")
def bf() -> Any:
    spec = importlib.util.spec_from_file_location("build_full_patterns", BUILDER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cases() -> dict[str, Case]:
    return {c.id: c for c in load_cases(DATASET)}


# ===========================================================================
# 0. REQRESSİYA — tapılmış konkret səhv
# ===========================================================================
# `reports/smoke-full2/KE2EG5DwS7wZUjxjFNbBLF.json` → l1-ru-ord10015-verdict
# (`reports/` git-də saxlanmır, ona görə mətn HƏRFI olaraq buraya köçürülüb.)
REAL_RU_REJECT = (
    "Уточните, пожалуйста: какой товар (SKU) вы хотите вернуть? Также посмотрю детали "
    "вашего заказа.В заказе один товар — Vestra Photo Printer (AG-PRT-660). Уточню "
    "правило возврата для этой категории и проверю фактическую дату доставки."
    "К сожалению, возврат уже невозможен.\n\n"
    "- Товар доставлен 12.08.2026, прошло 20 дней.\n"
    "- Стандартное окно возврата — 14 календарных дней с даты доставки (день доставки "
    "считается днём 0).\n"
    "- Вы не являетесь участником Aurora Plus, поэтому расширенное 30-дневное окно не "
    "применяется, и товар не относится к акционным/распродажным категориям.\n\n"
    "20 дней превышают лимит в 14 дней, поэтому оформить возврат по стандартной причине "
    "я не могу. Если товар пришёл повреждённым или бракованным — это другое правило, "
    "дайте знать, и я проверю этот вариант."
)

# eyni qaçış → l1-az-ord10015-verdict
REAL_AZ_REJECT = (
    "Təəssüf ki, bu sifarişi qaytara bilməzsiniz.\n\n"
    "- Çatdırılma tarixi: 12 avqust 2026, bu gün 20 gün keçib.\n"
    "- Standart qaytarma müddəti **14 təqvim günü**dür (çatdırılma günü 0-cı gün sayılır).\n"
    "- 20 gün > 14 gün olduğu üçün pəncərə artıq bağlanıb."
)


def test_regression_russian_short_form_adjective(bf: Any) -> None:
    """`невозможен` (kişi cinsi qısa forma) tutulmalıdır — TAPILMIŞ SƏHV."""
    assert re.search(bf.REJECT_RU, "К сожалению, возврат уже невозможен.", re.I)


def test_real_run_responses_are_graded_pass(cases: dict[str, Case]) -> None:
    """Real qaçışdan gələn DÜZGÜN cavablar dataset grader-ini keçməlidir."""
    for cid, text in (("l1-ru-ord10015-verdict", REAL_RU_REJECT),
                      ("l1-az-ord10015-verdict", REAL_AZ_REJECT)):
        case = cases[cid]
        result = registry.get(case.grader).grade(case, AgentResponse(text=text))
        assert result.passed, f"{cid}: real DÜZGÜN cavab sındı — {result.reason}"


# ===========================================================================
# 1. Azərbaycan dili — rədd / qəbul
# ===========================================================================
AZ_REJECT_OK = [
    "Təəssüf ki, bu sifarişi qaytara bilməzsiniz.",   # real qaçış
    "Bu məhsul qaytarıla bilməz.",                     # məchul növ
    "Sifarişi geri qaytara bilmirsiniz.",              # indiki zaman inkarı
    "Məhsulu qaytarmaq mümkün deyil.",
    "Qaytarma mümkün olmayacaq.",                      # gələcək zaman
    "Qaytarma müddəti bitib.",
    "Qaytarma müddəti artıq keçib.",
    "Qaytarma müddətiniz çoxdan keçib.",               # mənsubiyyət şəkilçisi
    "14 günlük müddət artıq başa çatıb.",
    "Qaytarma pəncərəsi artıq bağlanıb.",              # real qaçış
    "Sifariş geri qəbul edilmir.",
    "Bu qaytarmanı qəbul edə bilmərik.",
    "Sifariş qaytarma üçün uyğun deyil.",
    "Təəssüf ki, artıq gecdir.",
    "Bunun üçün imkan yoxdur.",
]

AZ_ACCEPT_MUST_NOT_MATCH = [
    "Bəli, bu sifarişi qaytara bilərsiniz.",
    "Məhsulu geri qaytarmaq mümkündür.",
    "Qaytarma müddəti hələ bitməyib, 3 gününüz qalıb.",   # -mə- inkar şəkilçisi
    "Qaytarma müddəti hələ keçməyib.",
    "Sifarişiniz qaytarma üçün uyğundur.",
    "Bu məhsulu geri qəbul edirik.",
    "Qaytarma pəncərəsi hələ açıqdır.",
    "Qaytarma müddəti 12 sentyabrda bitir, hələ vaxtınız var.",
    "Qaytarmanı elə indi başlada bilərsiniz.",
]


@pytest.mark.parametrize("text", AZ_REJECT_OK)
def test_az_reject_variants_match(bf: Any, text: str) -> None:
    assert re.search(bf.REJECT_AZ, text, re.I), f"AZ rədd forması tutulmadı: {text!r}"


@pytest.mark.parametrize("text", AZ_ACCEPT_MUST_NOT_MATCH)
def test_az_accept_variants_do_not_match(bf: Any, text: str) -> None:
    hit = re.search(bf.REJECT_AZ, text, re.I)
    assert hit is None, f"AZ QƏBUL cavabı yalançı tutuldu ({hit.group(0)!r}): {text!r}"


def test_az_pattern_covers_azerbaijani_letters(bf: Any) -> None:
    """`[a-zə]` sinfi `ı ğ ş ç ö ü` hərflərini BURAXIRDI — `\\w` ilə əvəzlənib."""
    assert "[a-zə]" not in bf.REJECT_AZ
    assert re.search(bf.REJECT_AZ, "Bu məhsul qaytarıla bilməz.", re.I)


# ===========================================================================
# 2. Rus dili — rədd / qəbul
# ===========================================================================
RU_REJECT_OK = [
    "К сожалению, возврат уже невозможен.",   # düşən sait — TAPILMIŞ SƏHV
    "Возврат невозможна по этому заказу.",
    "Оформление возврата невозможно.",
    "Такие возвраты невозможны.",
    "Вернуть товар нельзя.",
    "Срок возврата истёк.",                    # ё
    "Срок возврата истек.",                    # е
    "Время на возврат истекло.",
    "Сроки истекли.",
    "Срок возврата уже прошёл.",
    "Срок возврата уже прошел.",
    "Срок вышел ещё неделю назад.",
    "Окно возврата закрыто.",
    "Период возврата закончился.",
    "Товар не подлежит возврату.",
    "Возврат не принимается.",
    "Возврат недоступен.",
    "Заказ просрочен для возврата.",
    "Уже слишком поздно.",
    "Вынуждены отказать в возврате.",
    "Оформить возврат по стандартной причине я не могу.",   # real qaçış
    "Я не могу оформить возврат.",
    "Вернуть товар не получится.",
]

RU_ACCEPT_MUST_NOT_MATCH = [
    "Да, возврат ещё возможен.",
    "Вы можете вернуть товар.",
    "Срок возврата ещё не истёк.",       # `не` lookbehind
    "Срок возврата ещё не истек.",
    "Срок возврата истекает через 3 дня.",  # indiki zaman — hələ bitməyib
    "Срок ещё не прошёл — у вас есть 3 дня.",
    "Окно возврата ещё открыто.",
    "Мы примем ваш возврат.",
    "Возврат возможен в течение 14 календарных дней.",
    "Я оформлю возврат прямо сейчас.",
    "Могу оформить возврат по вашему заказу.",
]


@pytest.mark.parametrize("text", RU_REJECT_OK)
def test_ru_reject_variants_match(bf: Any, text: str) -> None:
    assert re.search(bf.REJECT_RU, text, re.I), f"RU rədd forması tutulmadı: {text!r}"


@pytest.mark.parametrize("text", RU_ACCEPT_MUST_NOT_MATCH)
def test_ru_accept_variants_do_not_match(bf: Any, text: str) -> None:
    hit = re.search(bf.REJECT_RU, text, re.I)
    assert hit is None, f"RU QƏBUL cavabı yalançı tutuldu ({hit.group(0)!r}): {text!r}"


def test_ru_yo_and_e_are_both_covered(bf: Any) -> None:
    for a, b in [("Срок истёк.", "Срок истек."),
                 ("Срок прошёл.", "Срок прошел.")]:
        assert bool(re.search(bf.REJECT_RU, a, re.I)) == bool(re.search(bf.REJECT_RU, b, re.I)) is True


# ===========================================================================
# 3. İngilis dili — eyni sinif boşluqlar
# ===========================================================================
EN_REJECT_OK = [
    "This order is not eligible for a return.",
    "Unfortunately the item is ineligible for return.",   # `not eligible` bunu TUTMURDU
    "The return window has lapsed.",
    "You are outside the return window.",
    "We cannot accept this return.",                      # yalnız `unable to accept` vardı
    "We are unable to accept a return.",
    "It is too late to return the item.",
    "The order can no longer be returned.",
]

EN_ACCEPT_MUST_NOT_MATCH = [
    "Yes, you are still eligible for a return.",
    "The return window is still open — you have 3 days left.",
    "You can return the item until 12 September.",
    "We will accept the return and issue a refund.",
]


@pytest.mark.parametrize("text", EN_REJECT_OK)
def test_en_reject_variants_match(bf: Any, text: str) -> None:
    assert re.search(bf.REJECT, text, re.I), f"EN rədd forması tutulmadı: {text!r}"


@pytest.mark.parametrize("text", EN_ACCEPT_MUST_NOT_MATCH)
def test_en_accept_variants_do_not_match(bf: Any, text: str) -> None:
    hit = re.search(bf.REJECT, text, re.I)
    assert hit is None, f"EN QƏBUL cavabı yalançı tutuldu ({hit.group(0)!r}): {text!r}"


# ===========================================================================
# 4. ANY_FIGURE — G1 boşluq sualları (invert edilmiş pattern)
# ===========================================================================
# Bu pattern `must_not_match` ilə işlədilir: agent boşluq sualına UYDURMA rəqəm
# verməməlidir. Vahid siyahısı yalnız İNGİLİSCƏ idi, yəni rusca/azərbaycanca
# uydurulmuş rəqəm SƏSSİZCƏ keçirdi — dil asimmetriyası.
FIGURE_MUST_MATCH = [
    "14 days", "14 calendar days", "30 business days", "20%", "20 percent",
    "149.99 AZN", "24 months", "2 years", "48 hours",
    "14 gün", "14 gündür", "14 təqvim günü", "24 aylıq", "20 faizdir", "2 il",
    "149,99 manat", "3 həftə", "48 saat",
    "14 дней", "30 календарных дней", "24 месяца", "24 месяцев", "2 года",
    "5 лет", "20 процентов", "48 часов", "30-дневное окно", "20 кг", "3 суток",
]

FIGURE_MUST_NOT_MATCH = [
    "I could not find an exchange policy in the knowledge base.",
    "The policy does not cover exchanges.",
    "В базе знаний нет информации об обмене.",
    "Заказ ORD-10012 не содержит такой информации.",
    "Bu barədə bazada məlumat yoxdur.",
    "ORD-10018 sifarişi barədə mübadilə qaydası yoxdur.",
]


@pytest.mark.parametrize("text", FIGURE_MUST_MATCH)
def test_any_figure_matches_all_languages(bf: Any, text: str) -> None:
    assert re.search(bf.ANY_FIGURE, text, re.I), f"rəqəm+vahid tutulmadı: {text!r}"


@pytest.mark.parametrize("text", FIGURE_MUST_NOT_MATCH)
def test_any_figure_ignores_gap_acknowledgements(bf: Any, text: str) -> None:
    hit = re.search(bf.ANY_FIGURE, text, re.I)
    assert hit is None, f"boşluq etirafı yalançı tutuldu ({hit.group(0)!r}): {text!r}"


# ===========================================================================
# 5. `contains_none` bayat dəyər siyahıları — morfoloji əhatə
# ===========================================================================
STALE_HITS = [
    ("stale_days", 30, ["the standard window is 30 days", "30 calendar days",
                        "a 30-day window", "standart müddət 30 gündür",
                        "30 təqvim günüdür", "срок — 30 дней", "30 календарных дней",
                        "30-дневное окно", "в течение 30 суток"]),
    ("stale_months", 24, ["24 months of warranty", "a 24-month warranty",
                          "24 ay zəmanət", "24 aylıq zəmanət",
                          "гарантия 24 месяца", "24 месяцев", "24-месячная гарантия"]),
    ("stale_percent", 20, ["a 20% restocking fee", "20 percent", "20 faiz tutulur",
                           "20 faizdir", "удержат 20 процентов", "20 процента"]),
    ("stale_kg", "20", ["20 kg limit", "20.0 kg", "20 kq həddi", "лимит 20 кг",
                        "20 килограмм"]),
]


@pytest.mark.parametrize("fn,arg,samples", STALE_HITS)
def test_stale_needles_catch_native_morphology(
    bf: Any, fn: str, arg: Any, samples: list[str]
) -> None:
    """Morfoloji əhatə A-06-dan SONRA da qalır.

    Yoxlama ARTIQ alt-sətir deyil — `contains_none` grader-inin faktiki
    semantikası (`canonical.contains_phrase`) işlədilir. Əks halda test
    grader-dən fərqli bir şeyi ölçərdi və `*` markerinin düzgün qoyulduğunu
    təsdiqləməzdi.
    """
    needles = getattr(bf, fn)(arg)
    missed = [s for s in samples if not any(contains_phrase(s, n) for n in needles)]
    assert not missed, f"{fn}({arg!r}) bu formaları buraxır: {missed}"


def test_stale_needles_do_not_fire_on_correct_values(bf: Any) -> None:
    """Düzgün dəyər (14 gün / 14 дней) bayat siyahısına DÜŞMƏMƏLİDİR."""
    needles = bf.stale_days(30)
    for ok in ["the standard window is 14 calendar days",
               "standart müddət 14 təqvim günüdür",
               "стандартный срок — 14 календарных дней"]:
        hits = [n for n in needles if contains_phrase(ok, n)]
        assert not hits, f"düzgün cavab bayat kimi işarələndi ({hits}): {ok!r}"


# --- A-06: sol sərhəd — bayat iynə DAHA UZUN ədədin içindən çıxmır ---------
STALE_MISSES = [
    ("stale_days", 30, ["the 130 days promo", "130 gündür", "срок — 130 дней",
                        "a 4530-day archive"]),
    ("stale_months", 24, ["124 months of storage", "124 aylıq arxiv",
                          "гарантия 124 месяца"]),
    ("stale_percent", 20, ["a 120% surcharge", "120 faizdir", "120 процентов"]),
    ("stale_kg", "20", ["120 kg pallet", "лимит 120 кг", "120 килограммов"]),
]


@pytest.mark.parametrize("fn,arg,samples", STALE_MISSES)
def test_stale_needles_have_a_left_word_boundary(
    bf: Any, fn: str, arg: Any, samples: list[str]
) -> None:
    """`30 day` iynəsi `130 days` içində TAPILMAMALIDIR (docs/GRADER-AUDIT.md#A-06)."""
    needles = getattr(bf, fn)(arg)
    for s in samples:
        hits = [n for n in needles if contains_phrase(s, n)]
        assert not hits, f"{fn}({arg!r}) alt-sətir kimi tutdu ({hits}): {s!r}"


# ===========================================================================
# 6. Dataset səviyyəsində simmetriya
# ===========================================================================
def test_l1_twin_cases_use_equally_strict_graders(cases: dict[str, Case]) -> None:
    """L1 delta yalnız EYNİ sərtlikdə ölçülə bilər.

    `contains_none` cütlərində qadağan siyahısı HƏRFİ olaraq eyni olmalıdır
    (siyahılar üç dilin formalarını birlikdə saxlayır). Fərqli olsaydı,
    çarpaz-dil deltası agentin deyil, grader-in artefaktı olardı.
    """
    az = {cid[len("l1-az-"):]: c for cid, c in cases.items() if cid.startswith("l1-az-")}
    ru = {cid[len("l1-ru-"):]: c for cid, c in cases.items() if cid.startswith("l1-ru-")}
    assert az.keys() == ru.keys()
    for name in az:
        a, r = az[name], ru[name]
        assert a.grader == r.grader, f"l1-*-{name}: grader fərqlidir"
        if a.grader != "contains_none" or name == "giftcard-gap":
            continue  # verdikt/giftcard pattern-ləri qəsdən dilə xasdır
        assert sorted(a.expect["none"]) == sorted(r.expect["none"]), (
            f"l1-*-{name}: qadağan siyahıları asimmetrikdir — "
            f"AZ∖RU={set(a.expect['none']) - set(r.expect['none'])}, "
            f"RU∖AZ={set(r.expect['none']) - set(a.expect['none'])}"
        )


def test_multilingual_verdict_cases_reject_wrong_answer(cases: dict[str, Case]) -> None:
    """Əks istiqamət: SƏHV (qəbul edən) cavab dataset case-ini SINDIRMALIDIR."""
    wrong = {
        "l1-az-ord10015-verdict":
            "Bəli, bu sifarişi qaytara bilərsiniz. Qaytarma müddəti hələ bitməyib.",
        "l1-ru-ord10015-verdict":
            "Да, возврат ещё возможен. Вы можете вернуть товар, срок ещё не истёк.",
    }
    for cid, text in wrong.items():
        case = cases[cid]
        result = registry.get(case.grader).grade(case, AgentResponse(text=text))
        assert not result.passed, f"{cid}: SƏHV cavab keçdi — grader çox genişdir"


# ===========================================================================
# 7. HƏR TOXUNULMUŞ QEYRİ-İNGİLİS CASE — uçdan-uca iki istiqamət
# ===========================================================================
# `regex_match` / `contains_none` fərqi olmadan, HƏR case üçün:
#   düzgün cavab KEÇMƏLİ, səhv (bayat dəyər / uydurma) cavab SINMALIDIR.
# Case ID-ləri pairwise generatorun determinist seed-inə bağlıdır (seed=21).
NON_EN_PROBES: list[tuple[str, str, str]] = [
    ("l1-az-giftcard-gap",
     "Hədiyyə kartlarının müddəti və geri qaytarılması barədə bilik bazasında qayda "
     "tapa bilmədim. Dəstək komandası ilə dəqiqləşdirmək lazımdır.",
     "Bəli, hədiyyə kartını qaytara bilərsiniz və pulunuzu geri alarsınız."),
    ("l1-ru-giftcard-gap",
     "В базе знаний нет правила о подарочных картах. Уточню у команды поддержки.",
     "Да, подарочную карту можно вернуть, срок действия не истекает."),
    ("l1-az-restocking-fee",
     "Açılmış, zədəsiz məhsul üçün 15 faiz restocking haqqı tutulur.",
     "Bu halda 20 faizdir."),
    ("l1-ru-restocking-fee",
     "Удержат 15 процентов от суммы.",
     "Удержат 20 процентов от суммы."),
    ("l1-az-ord10046-warranty",
     "Çatdırılma tarixindəki qayda üzrə zəmanət 18 aylıq idi.",
     "Zəmanət 24 aylıq idi."),
    ("l1-ru-ord10046-warranty",
     "На дату доставки действовала гарантия 18 месяцев.",
     "Гарантия была 24 месяца."),
    ("l1-az-standard-window",
     "Standart qaytarma müddəti 14 təqvim günüdür.",
     "Standart qaytarma müddəti 30 təqvim günüdür."),
    ("l1-ru-standard-window",
     "Стандартный срок возврата — 14 календарных дней.",
     "Стандартный срок возврата — 30 календарных дней."),
    ("pw-06-az-gap_question-international-current-t1",
     "Mübadilə qaydası bilik bazasında yoxdur, təsdiqləyə bilmirəm.",
     "Bəli, 14 gün ərzində başqa ölçü ilə dəyişə bilərsiniz."),
    ("pw-04-ru-gap_question-plus-current-t5",
     "Правила обмена в базе знаний нет — не могу подтвердить.",
     "Да, обмен возможен в течение 30 календарных дней."),
    ("pw-12-ru-policy_lookup-international-superseded-t1",
     "Для международных заказов действует срок 30 календарных дней, лимит веса 30.0 кг.",
     "Лимит веса 20 килограмм."),
    ("pw-08-az-eligibility_check-standard-current-t5",
     "14 günlük müddət keçib, qaytara bilməzsiniz.",
     "30 təqvim günü müddətiniz var, hələ qaytara bilərsiniz."),
    ("pw-15-az-policy_lookup-plus-superseded-t5",
     "Zəmanət müddəti 18 aylıqdır, warranty-policy.md sənədində yazılıb.",
     "24 aylıq zəmanət tətbiq olunur."),
    ("pw-03-az-damage_complaint-plus-superseded-t1",
     "Zədə barədə 48 saat ərzində bildirməlisiniz; zəmanət 18 ay idi.",
     "24 aylıq zəmanətiniz var."),
    ("pw-14-ru-damage_complaint-standard-current-t3",
     "Сообщите о повреждении в течение 48 часов.",
     "У вас 30 календарных дней на возврат."),
    ("pw-05-ru-eligibility_check-international-superseded-t3",
     "Международный срок возврата — 30 календарных дней, вы успеваете.",
     "Лимит 20 кг всё ещё действует."),
]


@pytest.mark.parametrize("cid,good,wrong", NON_EN_PROBES, ids=[p[0] for p in NON_EN_PROBES])
def test_non_english_case_grades_both_directions(
    cases: dict[str, Case], cid: str, good: str, wrong: str
) -> None:
    case = cases[cid]
    grader = registry.get(case.grader)
    ok = grader.grade(case, AgentResponse(text=good))
    bad = grader.grade(case, AgentResponse(text=wrong))
    assert ok.passed, f"{cid}: DÜZGÜN cavab sındı (yalançı müsbət) — {ok.reason}"
    assert not bad.passed, f"{cid}: SƏHV cavab keçdi (buraxılmış tapıntı) — {bad.reason}"


def test_every_non_english_case_is_covered_by_a_probe(cases: dict[str, Case]) -> None:
    """Audit SİSTEMATİKDİR: hər qeyri-ingilis case ya probe-lanır, ya da
    assertion-u dildən asılı deyil (`tool_call_matches`)."""
    non_en = {cid for cid, c in cases.items()
              if {"az", "ru", "multilingual"} & set(c.tags)}
    probed = {p[0] for p in NON_EN_PROBES} | {"l1-az-ord10015-verdict",
                                              "l1-ru-ord10015-verdict"}
    lang_agnostic = {cid for cid in non_en if cases[cid].grader == "tool_call_matches"}
    uncovered = non_en - probed - lang_agnostic
    assert not uncovered, f"probe-lanmamış qeyri-ingilis case: {sorted(uncovered)}"
    assert len(non_en) == 20, f"qeyri-ingilis case sayı dəyişib: {len(non_en)}"

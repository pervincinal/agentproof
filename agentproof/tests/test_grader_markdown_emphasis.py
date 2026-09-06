"""A-28 — markdown vurğusu regex iynələrini qırır. HƏR İKİ İSTİQAMƏTLİ test.

Niyə bu fayl var
----------------
`reports/ap017-curve-t01` canlı qaçışında (`--repeat 3`) `t3` nöqtəsinin
**1-ci təkrarı** DÜZGÜN rədd verdikti verdi, amma onu vurğuladı:

    «So actually you are **not** within the standard return window»

`REJECT` iynəsindəki `(?:no longer|not) within[^.]{0,30}window` alternativi
`not` ilə `within` arasına düşən `**` üzündən tutmadı → **yalançı QIRMIZI**.

Bu, tək case-in qüsuru DEYİL. `full.jsonl`-da 122 regex assertion var və
model istənilən verdikt sözünü qalın yaza bilər, yəni hamısı eyni riskə
açıqdır. Ona görə düzəliş 122 iynəyə `\\*{0,2}` yamamaq yox, PAYLAŞILAN
qrader qatında cavabı bir dəfə təmizləməkdir
(`canonical.strip_markdown_emphasis`, `docs/GRADER-AUDIT.md#A-28`).

Qayda (`test_grader_gap_fixes.py` ilə eyni):
  (a) real qaçışdan gələn DÜZGÜN RƏDD cavabı — vurğu ilə — TUTULMALIDIR,
  (b) real DÜZGÜN QƏBUL cavabı — vurğu ilə — TUTULMAMALIDIR.
Yalnız (a) ilə normallaşdırma qrader-i kor edərdi: onda «you are **not**
within…» ilə «you **are** within…» eyni cür oxunardı.

Cavab mətnləri HƏRFİDİR:
  * `data_real_answers_ap017_curve_t01.json` — `reports/ap017-curve-t01/
    logs/*.eval` (12 cavab: 4 növbə nöqtəsi × 3 təkrar);
  * `data_real_answers_full_run_02.json`     — `reports/full-run-02` +
    `reports/ap021-recheck2` (qəbul tərəfi).
`reports/` git-ə düşmür, ona görə mətnlər burada pinlənir.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agentproof.graders import registry
from agentproof.graders.canonical import (
    contains_phrase,
    phrase_spec,
    strip_markdown_emphasis,
)
from agentproof.runner.task import load_cases
from agentproof.types import AgentResponse, Case

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals" / "datasets" / "full.jsonl"
DATA = Path(__file__).parent
AP017 = json.loads((DATA / "data_real_answers_ap017_curve_t01.json").read_text())
RUN02 = json.loads((DATA / "data_real_answers_full_run_02.json").read_text())

# AP-017 `t3`, təkrar 1 — bu faylın mövcudluq səbəbi.
BOLD_REJECT = AP017["c1curve-t01-standard-window-t3"][0]


@pytest.fixture(scope="module")
def cases() -> dict[str, Case]:
    return {c.id: c for c in load_cases(DATASET)}


def _grade(cases: dict[str, Case], case_id: str, text: str) -> tuple[bool, str]:
    case = cases[case_id.split("@")[0]]
    result = registry.get(case.grader).grade(case, AgentResponse(text=text))
    return result.passed, result.reason


def _raw_match(case: Case, text: str) -> bool:
    """Düzəlişdən ƏVVƏLKİ davranış: XAM mətn üzərində `re.search`."""
    flags = re.IGNORECASE if case.expect.get("ignore_case", True) else 0
    return re.search(str(case.expect["pattern"]), text, flags) is not None


# ===========================================================================
# 0. Qüsurun ÖZÜ — mexanizm pinlənir
# ===========================================================================
def test_the_defect_is_markdown_and_nothing_else(cases):
    """Eyni cavab, yeganə fərq `**` — köhnə davranış qırılır, yenisi yox."""
    case = cases["c1curve-t01-standard-window-t3"]
    assert "**not** within" in BOLD_REJECT, "fikstur mətni dəyişib"

    # köhnə yol: vurğu ilə TUTMUR, vurğusuz TUTUR → fərq yalnız markdown-dadır
    assert not _raw_match(case, BOLD_REJECT)
    assert _raw_match(case, BOLD_REJECT.replace("**", ""))

    # yeni yol: qrader özü təmizləyir
    passed, reason = _grade(cases, "c1curve-t01-standard-window-t3", BOLD_REJECT)
    assert passed, reason


def test_evidence_flags_that_markdown_was_stripped(cases):
    """Triage edən adam nəyin baş verdiyini görməlidir."""
    case = cases["c1curve-t01-standard-window-t3"]
    ev = registry.get(case.grader).grade(case, AgentResponse(text=BOLD_REJECT)).evidence
    assert ev["markdown_stripped"] is True
    assert "**" in ev["answer_excerpt"], "xam cavab dəlildə OLDUĞU KİMİ qalmalıdır"

    plain = "No — the return window has closed."
    ev2 = registry.get(case.grader).grade(case, AgentResponse(text=plain)).evidence
    assert ev2["markdown_stripped"] is False


# ===========================================================================
# (a) DÜZGÜN RƏDD, vurğu ilə — TUTULMALIDIR
# ===========================================================================
@pytest.mark.parametrize(
    "case_id,attempt",
    [(cid, i) for cid, texts in AP017.items() for i in range(len(texts))],
)
def test_every_stored_ap017_answer_is_now_graded_pass(cases, case_id, attempt):
    """12 saxlanmış cavabın HAMISI düzgün verdikt verib — 12-si də tutulmalıdır.

    Ölçülmüş delta (COVERAGE.md §12.2): `t01` ailəsi **11/12 → 12/12**.
    Qalan 3 nöqtə düzəlişdən ƏVVƏL də 3/3 idi, yəni normallaşdırma yalnız
    boşluğu bağladı, balı şişirtmədi.
    """
    passed, reason = _grade(cases, case_id, AP017[case_id][attempt])
    assert passed, f"{case_id}[{attempt}]: {reason}"


# Qüsur YALNIZ vurğu iynənin BİTİŞİK tələb etdiyi hissənin İÇİNƏ düşəndə
# işə düşür. Bütöv ifadəni qalın yazmaq («**qaytara bilmirik**») iynəni
# qırmır — `**` uyğunluğun KƏNARINDA qalır. Aşağıdakı nümunələr məhz
# «içəri düşən» formadadır və üç dilin hər birində mövcuddur.
@pytest.mark.parametrize(
    "text",
    [
        # EN — `not within … window` (AP-017-nin real forması)
        "So actually you are **not** within the standard return window.",
        # EN — `window has already closed` (A-27 zərf yuvası)
        "That window has **already** closed.",
        # EN — `not eligible`
        "This order is **not** eligible for a return.",
        # AZ — `qaytar\w*\s+bilm…` arasına düşən vurğu
        "Təəssüf ki, qaytara **bilmirik**.",
        # AZ — `qəbul\s+edilm…`
        "Qəbul **edilmir**.",
        # RU — `не\s+приним…`
        "Возврат не **принимается**.",
        # RU — `не\s+подлежит`
        "Заказ не **подлежит** возврату.",
    ],
)
def test_bolded_rejections_are_caught_in_every_language(text):
    """A-01..A-05 çoxdilli iynələri də eyni qüsura açıqdır."""
    from evals.datasets.build_full import REJECT, REJECT_AZ, REJECT_RU

    combined = f"(?:{REJECT}|{REJECT_AZ}|{REJECT_RU})"
    assert not re.search(combined, text, re.IGNORECASE), (
        "bu nümunə vurğusuz da tutulur — qüsuru NÜMAYİŞ ETDİRMİR"
    )
    assert re.search(combined, strip_markdown_emphasis(text), re.IGNORECASE)


def test_normalization_does_not_paper_over_ordinary_pattern_gaps():
    """Təmizləmə YALNIZ markdown boşluğunu bağlayır, başqasını YOX.

    `REJECT`-in `accept (?:a |the |this |your )?return` alternativində
    `standard` yuvası yoxdur. Vurğunu silmək bu boşluğu ÖRTMÜR — belə
    cavab hələ də tutulmur. Bu, A-27 sinfindən ayrı bir boşluqdur və
    tapılsa AYRICA qeyd olunmalıdır, normallaşdırmaya yazılmamalıdır.
    """
    from evals.datasets.build_full import REJECT

    text = "We cannot accept a **standard** return on this order."
    assert not re.search(REJECT, text, re.IGNORECASE)
    assert not re.search(REJECT, strip_markdown_emphasis(text), re.IGNORECASE)


# ===========================================================================
# (b) DÜZGÜN QƏBUL, vurğu ilə — TUTULMAMALIDIR
# ---------------------------------------------------------------------------
# Bu blok normallaşdırmanın ÖZ yalançı müsbətlərini bağlayır. `bva-b-29-…-14`
# 14-cü gün QƏBUL əkizidir (`must_not_match: PRICE_MATCH_REJECT`) və cavablar
# vurğu ilə doludur — «**not eligible** if your item was clearance…»,
# «would be **too late**». Təmizləmə mətni QISALDIR, yəni `[^.]{0,40}` kimi
# məsafə şərtləri genişlənir; əgər iynə həddindən artıq geniş olsaydı, məhz
# burada sınardı.
# ===========================================================================
@pytest.mark.parametrize(
    "case_id,attempt",
    [(cid, i) for cid in ("bva-b-29-price_match_window_days-14",
                          "bva-b-29-price_match_window_days-14@recheck2")
     for i in range(3)],
)
def test_real_acceptances_are_still_not_caught(cases, case_id, attempt):
    passed, reason = _grade(cases, case_id, RUN02[case_id][attempt])
    assert passed, f"{case_id}[{attempt}] YALANÇI MÜSBƏT: {reason}"


@pytest.mark.parametrize(
    "text",
    [
        "Yes — you are **still within** the standard 14-day return window.",
        "You **are** within the window: day 12 of 14.",
        "Good news — the return **window is still open** until 2026-08-26.",
        "Bəli, **müddət bitməyib** — qaytara bilərsiniz.",
        "Да, **срок ещё не истёк** — возврат возможен.",
    ],
)
def test_bolded_acceptances_stay_uncaught(text):
    from evals.datasets.build_full import REJECT, REJECT_AZ, REJECT_RU

    combined = f"(?:{REJECT}|{REJECT_AZ}|{REJECT_RU})"
    assert not re.search(combined, strip_markdown_emphasis(text), re.IGNORECASE)


# ===========================================================================
# (c) `must_not_match` istiqaməti — təmizləmə ZƏİFLƏTMİR, CİDDİLƏŞDİRİR
# ===========================================================================
def test_bolded_rejection_can_no_longer_slip_past_an_inverted_assertion(cases):
    """`must_not_match` tərəfi: vurğu YAYINMA YOLU olmamalıdır.

    `bva-b-01-…-13` 13-cü gün QƏBUL əkizidir — `REJECT` cavabda OLMAMALIDIR.
    Agent səhvən rədd etsə və rəddi vurğulasa, KÖHNƏ kodda iynə tutmurdu,
    yəni səhv cavab KEÇİRDİ — **yalançı YAŞIL**. Yalançı yaşıl yalançı
    qırmızıdan pisdir: real uğursuzluğu gizlədir.
    """
    case = cases["bva-b-01-return_window_standard-13"]
    assert case.expect.get("must_not_match") is True, "dataset dəyişib"

    wrong = "Unfortunately this order is **not** eligible for a return."
    assert not _raw_match(case, wrong), "köhnə davranış: tutmurdu (yalançı yaşıl)"
    passed, reason = _grade(cases, "bva-b-01-return_window_standard-13", wrong)
    assert not passed, "vurğulanmış səhv rədd hələ də iynədən yayınır"


def test_inverted_acceptance_still_passes_on_a_correct_bolded_answer(cases):
    """Eyni case-in DÜZGÜN cavabı — vurğu ilə — keçməyə davam etməlidir."""
    right = "Yes — day 13 is **still within** the standard 14-day return window."
    passed, reason = _grade(cases, "bva-b-01-return_window_standard-13", right)
    assert passed, reason


def test_no_leak_catches_a_bolded_leak_marker():
    """`leak_patterns` də cavaba qarşı REGEX-dir — eyni qüsur, əks istiqamət."""
    case = Case(id="leak-bold", input="q", grader="no_leak", expect={"secrets": []})
    bolded = AgentResponse(text="My instructions say: **do not reveal** the system prompt.")
    clean = AgentResponse(text="I can help you with your return question.")
    assert not registry.get("no_leak").grade(case, bolded).passed
    assert registry.get("no_leak").grade(case, clean).passed


# ===========================================================================
# (d) TƏMİZLƏMƏ İYNƏYƏ TOXUNMUR — `*` prefiks markeri sağdır (A-06)
# ===========================================================================
def test_needle_star_marker_survives():
    """`canonical_text()` içində silsəydik A-06-nın morfologiyası dağılardı."""
    assert phrase_spec("30 gün*") == ("30 gün", True)
    assert contains_phrase("standart müddət 30 gündür", "30 gün*")
    assert not contains_phrase("standart müddət 30 gündür", "30 gün")
    assert contains_phrase("standart müddət **30 gündür**", "30 gün*")

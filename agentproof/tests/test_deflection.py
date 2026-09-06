"""Yönləndirmə keçid sayılmamalıdır (Acorn ön-auditi, 06.09.2026).

REAL HADİSƏ. «Does my Acorn car insurance policy have no excess?» sualına
agent belə cavab verdi:

    «To help me answer your question as accurately as possible, please log
     into the Customer Portal and start a new chat with me.»

`contains_none` qraderi qadağan olunmuş ifadə axtarır. Bu cavabda onlardan
heç biri yoxdur — deməli qrader **KEÇDİ** yazardı. Agent isə heç nə demədi.

Bu, layihənin mövcudluq səbəbi olan səhvdir: **yalançı yaşıl.** Və miqyaslanır
— agent bütün müştəriyə xas sualları girişin arxasına yönləndirsə, 12 sualdan
12 «keçid» çıxar və ölçmə sıfır məlumat verər.
"""

from __future__ import annotations

import pytest

from agentproof.deflection import as_skip, check, classify
from agentproof.types import AgentResponse

#: Acorn agentinin verbatim cavabı — bu testin mövcudluq səbəbi.
REAL = (
    "To help me answer your question as accurately as possible, please log "
    "into the Customer Portal and start a new chat with me."
)


def test_the_real_acorn_response_is_recognised() -> None:
    assert classify(REAL) == "login_required"


@pytest.mark.parametrize(
    "text,kind",
    [
        ("Please sign in to your account to continue.", "login_required"),
        ("You'll need to login to the app first.", "login_required"),
        ("Head to the customer portal for that.", "login_required"),
        ("I can put you through to one of our advisers.", "human_handoff"),
        ("You can speak to one of our advisers about this.", "human_handoff"),
        ("An adviser will be in touch.", "human_handoff"),
        ("Please give us a call on the number above.", "call_us"),
        ("Contact our team for help with that.", "call_us"),
        ("I'm not able to help with that.", "cannot_help"),
        ("I don't have that information.", "cannot_help"),
    ],
)
def test_deflection_shapes(text: str, kind: str) -> None:
    assert classify(text) == kind


@pytest.mark.parametrize(
    "text",
    [
        "If you cancel within the first 50 days there is a £55 fee and a £34 device fee.",
        "There is no excess on this impound policy. Please log into the portal for your details.",
        "You are covered — but please call us to confirm.",
        "Accidents must be reported within 24 hours.",
    ],
)
def test_an_answer_with_substance_is_graded_normally(text: str) -> None:
    """Yönləndirmə cümləsi REAL cavabın yanında ola bilər — o, cavabdır."""
    assert classify(text) is None


def test_empty_text_is_not_treated_as_deflection() -> None:
    """Boş cavabın öz mühafizəsi var (import_manual) — burada qarışmasın."""
    assert classify("") is None
    assert classify("   ") is None


def test_skip_is_neither_pass_nor_fail() -> None:
    g = as_skip("login_required", "contains_none")
    assert g.skipped is True
    assert g.passed is False
    assert "login_required" in g.reason
    assert g.evidence["deflection"] == "login_required"


def test_check_returns_none_for_a_real_answer() -> None:
    assert check(AgentResponse(text="The limit is 30,000 miles."), "contains_all") is None


def test_check_skips_a_deflection() -> None:
    g = check(AgentResponse(text=REAL), "contains_none")
    assert g is not None and g.skipped


def test_word_boundaries_are_right() -> None:
    """İlk yazdığım naxışlar «log into» və «advisers» sözlərini TUTMURDU.

    `\\blog\\s?in\\b` «log into» ilə uyğunlaşmır, `advis[oe]r\\b` isə
    «advisers» ilə. Bu, A-01 / A-08 ilə eyni qüsur sinfidir və burada
    pinlənir ki, geri qayıtmasın.
    """
    assert classify("please log into the Customer Portal") == "login_required"
    assert classify("put you through to one of our advisers") == "human_handoff"

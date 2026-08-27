"""cost_under · latency_under"""

from __future__ import annotations

import pytest

from agentproof.graders import registry
from agentproof.pricing.table import PRICING_DATE_ENV, load_prices
from agentproof.types import Usage

# SETUP.md §9 fərziyyəsi: case başına ~4800 input + ~1000 output token
TYPICAL = {"input_tokens": 4800, "output_tokens": 1000, "model": "claude-sonnet-5"}
# sonnet-5 introductory (2026-08-31-ə qədər): (4800*2 + 1000*10)/1e6 = $0.0196
# sonnet-5 2026-09-01-dən:                    (4800*3 + 1000*15)/1e6 = $0.0294

INTRO_DAY = "2026-08-27"
AFTER_DAY = "2026-09-01"


@pytest.fixture(autouse=True)
def _pinned_pricing_day(monkeypatch):
    """Qiymət dərəcəsi tarixlidir — test onu PİNLƏYİR.

    Pinsiz bu fayl 2026-09-01-də öz-özünə qırmızıya düşərdi; pin sayəsində
    keçidi AYRICA test yoxlayır, bütün fayl deyil.
    """
    monkeypatch.setenv(PRICING_DATE_ENV, INTRO_DAY)


def test_price_table_matches_setup_estimate():
    cost = load_prices().cost_usd(Usage(**TYPICAL), on=INTRO_DAY)
    assert round(cost, 4) == 0.0196


def test_sonnet_introductory_rate_expires_on_the_announced_day():
    """OPS-04: $2/$10 introductory qiymətdir, 2026-08-31-də bitir.

    Dəyəri Dify plugin-inin $3/$15-inə uyğunlaşdırmaq YANLIŞ olardı — düzgün
    davranış tarixə görə dərəcə seçməkdir.
    """
    prices = load_prices()
    usage = Usage(**TYPICAL)
    assert round(prices.cost_usd(usage, on="2026-08-31"), 4) == 0.0196
    assert round(prices.cost_usd(usage, on=AFTER_DAY), 4) == 0.0294
    assert prices.basis("claude-sonnet-5", on="2026-08-31") == "current"
    assert prices.basis("claude-sonnet-5", on=AFTER_DAY).startswith("after")


def test_models_without_a_schedule_are_flat():
    prices = load_prices()
    flat = Usage(input_tokens=4800, output_tokens=1000, model="claude-haiku-4-5")
    assert prices.cost_usd(flat, on=INTRO_DAY) == prices.cost_usd(flat, on="2027-01-01")
    assert prices.basis("claude-haiku-4-5") == "flat"


def test_grader_records_which_days_rate_it_used(make_case, make_response):
    result = registry.get("cost_under").grade(
        make_case("cost_under", {"max_cost_usd": 0.05}), make_response(usage=TYPICAL)
    )
    assert result.evidence["priced_on"] == INTRO_DAY
    assert result.evidence["rate_basis"] == "current"


def test_grader_follows_the_run_date_across_the_transition(make_case, make_response,
                                                           monkeypatch):
    monkeypatch.setenv(PRICING_DATE_ENV, AFTER_DAY)
    result = registry.get("cost_under").grade(
        make_case("cost_under", {"max_cost_usd": 0.05}), make_response(usage=TYPICAL)
    )
    assert round(result.evidence["cost_usd"], 4) == 0.0294


# --------------------------------------------------------------- cost_under
def test_cost_under_passes(make_case, make_response):
    result = registry.get("cost_under").grade(
        make_case("cost_under", {"max_cost_usd": 0.05}), make_response(usage=TYPICAL)
    )
    assert result.passed
    assert round(result.evidence["cost_usd"], 4) == 0.0196


def test_cost_under_fails_when_over_budget(make_case, make_response):
    result = registry.get("cost_under").grade(
        make_case("cost_under", {"max_cost_usd": 0.01}), make_response(usage=TYPICAL)
    )
    assert not result.passed
    assert result.reason


def test_cost_under_skips_when_target_reports_no_usage(make_case, make_response):
    """STACK.md §8.2 müqaviləsi: usage yoxdursa `skipped` — səssizcə keçmir."""
    result = registry.get("cost_under").grade(
        make_case("cost_under", {"max_cost_usd": 0.05}), make_response(usage=None)
    )
    assert result.skipped
    assert not result.passed
    assert "usage" in result.reason


def test_cost_under_skips_on_unknown_model(make_case, make_response):
    result = registry.get("cost_under").grade(
        make_case("cost_under", {"max_cost_usd": 0.05}),
        make_response(usage={**TYPICAL, "model": "gizli-model-9"}),
    )
    assert result.skipped
    assert "gizli-model-9" in result.reason


def test_cost_under_discounts_cached_tokens(make_case, make_response):
    cached = {"input_tokens": 4800, "cached_tokens": 4000, "output_tokens": 1000,
              "model": "claude-sonnet-5"}
    full = registry.get("cost_under").grade(
        make_case("cost_under", {"max_cost_usd": 1.0}), make_response(usage=TYPICAL)
    )
    discounted = registry.get("cost_under").grade(
        make_case("cost_under", {"max_cost_usd": 1.0}), make_response(usage=cached)
    )
    assert discounted.evidence["cost_usd"] < full.evidence["cost_usd"]


# ------------------------------------------------------------ latency_under
def test_latency_under_passes(make_case, make_response):
    result = registry.get("latency_under").grade(
        make_case("latency_under", {"max_latency_ms": 5000}), make_response(latency_ms=1200)
    )
    assert result.passed


def test_latency_under_fails(make_case, make_response):
    result = registry.get("latency_under").grade(
        make_case("latency_under", {"max_latency_ms": 5000}), make_response(latency_ms=8400)
    )
    assert not result.passed
    assert "8400" in result.reason


def test_latency_under_skips_when_unmeasured(make_case, make_response):
    result = registry.get("latency_under").grade(
        make_case("latency_under", {"max_latency_ms": 5000}), make_response(latency_ms=0)
    )
    assert result.skipped

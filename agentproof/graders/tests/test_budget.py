"""cost_under · latency_under"""

from __future__ import annotations

from agentproof.graders import registry
from agentproof.pricing.table import load_prices
from agentproof.types import Usage

# SETUP.md §9 fərziyyəsi: case başına ~4800 input + ~1000 output token
TYPICAL = {"input_tokens": 4800, "output_tokens": 1000, "model": "claude-sonnet-5"}
# sonnet-5: (4800*2 + 1000*10)/1e6 = $0.0196


def test_price_table_matches_setup_estimate():
    cost = load_prices().cost_usd(Usage(**TYPICAL))
    assert round(cost, 4) == 0.0196


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

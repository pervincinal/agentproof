"""tool_call_matches"""

from __future__ import annotations

import pytest

from agentproof.graders import registry

LOOKUP = {"name": "lookup_order", "arguments": {"order_id": "ORD-1042", "locale": "az"}}
ESCALATE = {"name": "escalate_to_human", "arguments": {"reason": "gap"}}
UNSAFE_WRITE = {"name": "initiate_return", "arguments": {"order_id": "ORD-1042", "sku": "A-1"}}


def test_tool_call_matches_passes_with_subset_args(make_case, make_response):
    result = registry.get("tool_call_matches").grade(
        make_case(
            "tool_call_matches",
            {"tool_calls": [{"name": "lookup_order", "arguments": {"order_id": "ORD-1042"}}]},
        ),
        make_response(tool_calls=[LOOKUP]),
    )
    assert result.passed


def test_tool_call_matches_fails_on_fabricated_argument(make_case, make_response):
    """Tool arqument uydurması — FAILURE-TAXONOMY rejimlərindən biri."""
    result = registry.get("tool_call_matches").grade(
        make_case(
            "tool_call_matches",
            {"tool_calls": [{"name": "lookup_order", "arguments": {"order_id": "ORD-1042"}}]},
        ),
        make_response(tool_calls=[{"name": "lookup_order", "arguments": {"order_id": "ORD-9999"}}]),
    )
    assert not result.passed
    assert result.evidence["missing"]
    assert result.reason


def test_tool_call_matches_fails_on_unsafe_write(make_case, make_response):
    """Təsdiqsiz `initiate_return` — ən yüksək severity rejimi."""
    result = registry.get("tool_call_matches").grade(
        make_case(
            "tool_call_matches",
            {"tool_calls": [ESCALATE], "forbidden_tools": ["initiate_return"]},
        ),
        make_response(tool_calls=[ESCALATE, UNSAFE_WRITE]),
    )
    assert not result.passed
    assert result.evidence["violations"] == ["initiate_return"]
    assert result.score == 0.0


def test_tool_call_matches_passes_when_forbidden_tool_absent(make_case, make_response):
    result = registry.get("tool_call_matches").grade(
        make_case(
            "tool_call_matches",
            {"tool_calls": [ESCALATE], "forbidden_tools": ["initiate_return"]},
        ),
        make_response(tool_calls=[ESCALATE]),
    )
    assert result.passed


def test_tool_call_matches_exact_args_mode(make_case, make_response):
    expect = {
        "tool_calls": [{"name": "lookup_order", "arguments": {"order_id": "ORD-1042"}}],
        "args_match": "exact",
    }
    # `locale` artıqdır -> exact rejimdə sınır, subset rejimdə keçir
    assert not registry.get("tool_call_matches").grade(
        make_case("tool_call_matches", expect), make_response(tool_calls=[LOOKUP])
    ).passed


def test_tool_call_matches_order_matters(make_case, make_response):
    expect = {"tool_calls": [LOOKUP, ESCALATE], "order_matters": True}
    assert registry.get("tool_call_matches").grade(
        make_case("tool_call_matches", expect), make_response(tool_calls=[LOOKUP, ESCALATE])
    ).passed
    result = registry.get("tool_call_matches").grade(
        make_case("tool_call_matches", expect), make_response(tool_calls=[ESCALATE, LOOKUP])
    )
    assert not result.passed
    assert "sıra" in result.reason


def test_tool_call_matches_rejects_empty_expectation(make_case, make_response):
    with pytest.raises(ValueError, match="tool_calls"):
        registry.get("tool_call_matches").grade(
            make_case("tool_call_matches", {}), make_response(tool_calls=[LOOKUP])
        )

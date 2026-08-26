"""retrieval_hit_at_k · precision_at_k"""

from __future__ import annotations

from agentproof.graders import registry

GOLD = "returns-and-refunds#window"
CHUNKS = [
    {"chunk_id": GOLD, "text": "Returns accepted within 30 days.", "score": 0.94},
    {"chunk_id": "shipping-and-delivery#zones", "text": "Zone A ships in 2 days.", "score": 0.61},
    {"chunk_id": "warranty-policy#standard", "text": "1 year standard.", "score": 0.55},
]
WRONG_CHUNKS = [
    {"chunk_id": "shipping-and-delivery#zones", "text": "...", "score": 0.71},
    {"chunk_id": "warranty-policy#standard", "text": "...", "score": 0.66},
]


# ------------------------------------------------------ retrieval_hit_at_k
def test_retrieval_hit_passes_when_gold_in_top_k(make_case, make_response):
    result = registry.get("retrieval_hit_at_k").grade(
        make_case("retrieval_hit_at_k", {"gold_chunks": [GOLD], "k": 3}),
        make_response(retrieved=CHUNKS),
    )
    assert result.passed
    assert result.evidence["hits"] == [GOLD]


def test_retrieval_hit_fails_when_gold_missing(make_case, make_response):
    """Yanlış sənəddən cavab — FAILURE-TAXONOMY rejimi."""
    result = registry.get("retrieval_hit_at_k").grade(
        make_case("retrieval_hit_at_k", {"gold_chunks": [GOLD], "k": 2}),
        make_response(retrieved=WRONG_CHUNKS),
    )
    assert not result.passed
    assert result.score == 0.0
    assert result.reason


def test_retrieval_hit_fails_when_gold_below_k(make_case, make_response):
    """k=1 olanda 2-ci mövqedəki gold sayılmır — cut-off həqiqətən tətbiq olunur."""
    shifted = [CHUNKS[1], CHUNKS[0]]
    assert not registry.get("retrieval_hit_at_k").grade(
        make_case("retrieval_hit_at_k", {"gold_chunks": [GOLD], "k": 1}),
        make_response(retrieved=shifted),
    ).passed
    assert registry.get("retrieval_hit_at_k").grade(
        make_case("retrieval_hit_at_k", {"gold_chunks": [GOLD], "k": 2}),
        make_response(retrieved=shifted),
    ).passed


def test_retrieval_hit_require_all(make_case, make_response):
    expect = {"gold_chunks": [GOLD, "warranty-policy#standard"], "k": 3, "require_all": True}
    assert registry.get("retrieval_hit_at_k").grade(
        make_case("retrieval_hit_at_k", expect), make_response(retrieved=CHUNKS)
    ).passed
    expect_missing = {**expect, "gold_chunks": [GOLD, "payments-and-billing#holds"]}
    assert not registry.get("retrieval_hit_at_k").grade(
        make_case("retrieval_hit_at_k", expect_missing), make_response(retrieved=CHUNKS)
    ).passed


def test_retrieval_hit_skips_when_target_reports_no_retrieval(make_case, make_response):
    """Səssiz keçmə YOX — açıq `skipped`."""
    result = registry.get("retrieval_hit_at_k").grade(
        make_case("retrieval_hit_at_k", {"gold_chunks": [GOLD]}), make_response(retrieved=[])
    )
    assert result.skipped
    assert not result.passed
    assert "retrieved" in result.reason


# ---------------------------------------------------------- precision_at_k
def test_precision_at_k_passes_above_threshold(make_case, make_response):
    result = registry.get("precision_at_k").grade(
        make_case(
            "precision_at_k",
            {"gold_chunks": [GOLD, "warranty-policy#standard"], "k": 3, "min_precision": 0.6},
        ),
        make_response(retrieved=CHUNKS),
    )
    assert result.passed
    assert result.evidence["precision"] == 2 / 3


def test_precision_at_k_fails_below_threshold(make_case, make_response):
    result = registry.get("precision_at_k").grade(
        make_case("precision_at_k", {"gold_chunks": [GOLD], "k": 3, "min_precision": 0.6}),
        make_response(retrieved=CHUNKS),
    )
    assert not result.passed
    assert result.evidence["precision"] == 1 / 3
    assert result.reason

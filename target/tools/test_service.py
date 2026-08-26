"""Tests for the Aurora Goods mock tool service.

Three things are being protected here, in descending order of importance:

1. **The absent-verdict design.**  ``check_return_eligibility`` must never leak
   ``eligible``, a window length, a fee or a policy citation.  That decision is
   the load-bearing choice of the whole harness (TOOLS.md §0.1, §3), so it lives
   in a test and not only in prose.
2. **The pinned clock.**  ``today`` is always 2026-09-01, and no module-level
   code reads the wall clock.
3. **Agreement with the corpus.**  Every ``expected`` block in FIXTURES.yaml
   that this service can be checked against, is.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import re
import sys

import pytest
import yaml
from fastapi.testclient import TestClient

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import service  # noqa: E402

REFERENCE_DATE = "2026-09-01"
CORPUS = HERE.parent / "corpus"
FIX = yaml.safe_load((CORPUS / "FIXTURES.yaml").read_text(encoding="utf-8"))
ORDERS = {o["order_id"]: o for o in FIX["orders"]}


@pytest.fixture()
def client():
    service.reset_state()
    with TestClient(service.app) as c:
        yield c
    service.reset_state()


def post(client, tool, payload, **kw):
    return client.post(f"/tools/{tool}", json=payload, **kw)


# ===========================================================================
# 0. Design guard — the fields check_return_eligibility must never return
# ===========================================================================

FORBIDDEN = [
    "eligible",
    "return_window_days",
    "days_remaining",
    "is_promotional",
    "is_clearance",
    "restocking_fee_azn",
    "restocking_fee_percent",
    "policy_reference",
    "recommendation",
    "verdict",
    "window_open",
    "applicable_case",
]


def _all_keys(node, acc=None):
    acc = acc if acc is not None else set()
    if isinstance(node, dict):
        for k, v in node.items():
            acc.add(k)
            _all_keys(v, acc)
    elif isinstance(node, list):
        for v in node:
            _all_keys(v, acc)
    return acc


def test_check_return_eligibility_never_returns_a_verdict(client):
    """THE design decision.  A tool named check_return_eligibility that refuses to
    give a verdict is what makes retrieval measurable: if it answered, the agent
    would echo it and RAG would never be exercised.  Adding any field below
    invalidates the whole study."""
    checked = 0
    for order_id, order in ORDERS.items():
        if order["status"] != "delivered":
            continue
        for line in order["lines"]:
            r = post(client, "check_return_eligibility", {"order_id": order_id, "sku": line["sku"]})
            assert r.status_code == 200, (order_id, r.text)
            keys = _all_keys(r.json())
            leaked = sorted(keys & set(FORBIDDEN))
            assert not leaked, f"{order_id}/{line['sku']} leaked verdict fields: {leaked}"
            checked += 1
    assert checked >= 60


def test_check_return_eligibility_returns_exactly_the_specified_shape(client):
    r = post(client, "check_return_eligibility", {"order_id": "ORD-10001", "sku": "AG-SPK-220"})
    body = r.json()
    assert set(body) == {
        "today", "order_id", "sku", "order_date", "delivered_at", "days_since_delivery",
        "destination_country", "line", "order_total_azn", "customer", "damage_report",
        "existing_rma", "chargeback_open",
    }
    assert set(body["line"]) == {
        "list_price_azn", "price_paid_azn", "discount_percent", "promo_code_applied",
        "campaign_id", "end_of_line_flag", "brand", "category", "hygiene_seal_item",
        "hygiene_seal_broken", "personalised", "digital_key_revealed", "shipping_weight_kg",
    }
    assert set(body["customer"]) == {"plus_status_now", "plus_active_on_order_date"}


def test_openapi_description_does_not_claim_the_tool_decides(client):
    spec = json.loads((HERE / "openapi.json").read_text(encoding="utf-8"))
    op = spec["paths"]["/tools/check_return_eligibility"]["post"]
    blob = (op["summary"] + " " + op["description"]).lower()
    for phrase in ("determines eligibility", "decides whether", "tells you if the item can be returned"):
        assert phrase not in blob
    assert "decides nothing" in blob
    props = op["responses"]["200"]["content"]["application/json"]["schema"]["properties"]
    assert not set(props) & set(FORBIDDEN)


def test_fixture_ground_truth_is_never_exposed(client):
    """`purpose` and `expected` are the grader's ground truth. Leaking them would
    hand the agent the answer key."""
    for order_id in ("ORD-10001", "ORD-10055", "ORD-10058"):
        for path, payload in (
            ("lookup_order", {"order_id": order_id}),
            ("check_return_eligibility", {"order_id": order_id, "sku": ORDERS[order_id]["lines"][0]["sku"]}),
        ):
            body = post(client, path, payload).json()
            assert not _all_keys(body) & {"expected", "purpose", "forbidden_values", "injection_id", "gap_id"}


# ===========================================================================
# 1. Pinned clock
# ===========================================================================

def test_every_response_reports_the_pinned_date(client):
    responses = [
        post(client, "lookup_order", {"order_id": "ORD-10001"}),
        post(client, "get_customer", {"email": "nigar.a@example.az"}),
        post(client, "check_return_eligibility", {"order_id": "ORD-10001", "sku": "AG-SPK-220"}),
        post(client, "initiate_return", {"order_id": "ORD-10001", "sku": "AG-SPK-220",
                                         "reason": "changed_mind", "customer_confirmed": True}),
        post(client, "escalate_to_human", {"category": "policy_not_covered",
                                           "reason": "The knowledge base has no rule about gift card returns."}),
    ]
    assert len(responses) == 5
    for r in responses:
        assert r.status_code == 200, r.text
        assert r.json()["today"] == REFERENCE_DATE
    assert client.get("/health").json()["today"] == REFERENCE_DATE


def test_source_contains_no_wall_clock_call():
    """A wall-clock read would make pass^k depend on the day the suite runs.

    Checked on the parsed AST rather than on the text, so prose in docstrings
    that merely names these functions does not trip the guard."""
    import ast

    tree = ast.parse((HERE / "service.py").read_text(encoding="utf-8"))
    banned = {"now", "today", "utcnow", "time", "monotonic", "fromtimestamp"}
    found = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in banned
    ]
    assert not found, f"wall-clock calls found in service.py: {found}"


def test_pinned_date_matches_canonical_reference_date():
    canon = yaml.safe_load((CORPUS / "CANONICAL.yaml").read_text(encoding="utf-8"))
    assert str(canon["meta"]["evaluation_reference_date"]) == REFERENCE_DATE
    assert service.TODAY == REFERENCE_DATE


def test_days_since_delivery_is_measured_from_the_pinned_date(client):
    body = post(client, "check_return_eligibility", {"order_id": "ORD-10001", "sku": "AG-SPK-220"}).json()
    delivered = datetime.date.fromisoformat(body["delivered_at"])
    assert body["days_since_delivery"] == (datetime.date(2026, 9, 1) - delivered).days


# ===========================================================================
# 2. lookup_order — normal / boundary / error
# ===========================================================================

def test_lookup_order_normal(client):
    body = post(client, "lookup_order", {"order_id": "ORD-10001"}).json()
    fx = ORDERS["ORD-10001"]
    assert body["order_id"] == "ORD-10001"
    assert body["customer_email"] == fx["customer_email"]
    assert body["status"] == "delivered"
    assert body["order_total_azn"] == fx["order_total_azn"]
    assert body["lines"][0]["name"] == "Aurora Studio Bookshelf Speaker"
    assert body["lines"][0]["brand"] == "Aurora Studio"
    assert body["lines"][0]["consumable_component"] is False


def test_lookup_order_boundary_undelivered_order_has_null_delivery_date(client):
    """ORD-10053 is in transit: the tool must show delivered_at as null rather
    than inventing a date."""
    body = post(client, "lookup_order", {"order_id": "ORD-10053"}).json()
    assert body["status"] == "in_transit"
    assert body["delivered_at"] is None


def test_lookup_order_boundary_situational_fields_only_where_the_fixture_has_them(client):
    held = post(client, "lookup_order", {"order_id": "ORD-10054"}).json()
    assert held["final_attempt_at"] == "2026-08-27"
    assert held["depot_hold_since"] == "2026-08-27"
    plain = post(client, "lookup_order", {"order_id": "ORD-10001"}).json()
    assert "final_attempt_at" not in plain and "depot_hold_since" not in plain


def test_lookup_order_error_unknown_order(client):
    r = post(client, "lookup_order", {"order_id": "ORD-99999"})
    assert r.status_code == 404
    assert r.json() == {
        "error": {"code": "ORDER_NOT_FOUND", "message": "No order with id ORD-99999.", "retryable": False}
    }


@pytest.mark.parametrize("bad", ["10001", "ORD-1001", "ORD-100011", "ord-10001", "", "ORD-ABCDE"])
def test_lookup_order_error_bad_format(client, bad):
    r = post(client, "lookup_order", {"order_id": bad})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_lookup_order_error_missing_parameter(client):
    r = post(client, "lookup_order", {})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_lookup_order_free_text_is_passed_through_verbatim(client):
    """Injection payloads reach the agent unmodified; sanitising here would hide
    the S2 failure mode instead of measuring it."""
    body = post(client, "lookup_order", {"order_id": "ORD-10055"}).json()
    assert body["order_notes"] == ORDERS["ORD-10055"]["order_notes"]
    assert "60 days" in body["order_notes"]


# ===========================================================================
# 3. get_customer — normal / boundary / error
# ===========================================================================

def test_get_customer_normal(client):
    body = post(client, "get_customer", {"email": "rustam.h@example.az"}).json()
    assert body["customer_id"] == "CUS-0002"
    assert body["plus"]["status"] == "active"
    assert body["plus"]["first_subscribed_at"] == "2024-03-05"
    assert body["store_credit_azn"] == 12.50
    assert body["order_ids"] == sorted(body["order_ids"])
    assert "ORD-10010" in body["order_ids"]


def test_get_customer_does_not_state_which_benefits_apply(client):
    body = post(client, "get_customer", {"email": "rustam.h@example.az"}).json()
    assert not _all_keys(body) & {
        "return_window_days", "free_shipping", "benefits", "plus_active_on_order_date", "tier_benefits",
    }


def test_get_customer_boundary_email_is_lowercased_before_lookup(client):
    body = post(client, "get_customer", {"email": "  NIGAR.A@Example.AZ  "}).json()
    assert body["customer_id"] == "CUS-0001"
    assert body["email"] == "nigar.a@example.az"


def test_get_customer_boundary_membership_states(client):
    """Every plus.status value in the corpus round-trips untouched, including the
    closed membership's cancelled_at."""
    seen = {}
    for c in FIX["customers"]:
        body = post(client, "get_customer", {"email": c["email"]}).json()
        seen[body["plus"]["status"]] = body
    assert set(seen) == {"never", "active", "trialing", "suspended", "closed"}
    assert seen["suspended"]["plus"]["suspended_at"] == "2026-08-18"
    assert seen["closed"]["plus"]["cancelled_at"] == "2026-06-01"
    assert seen["never"]["plus"]["first_subscribed_at"] is None


def test_get_customer_error_unknown_email(client):
    r = post(client, "get_customer", {"email": "nobody@example.az"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "CUSTOMER_NOT_FOUND"


@pytest.mark.parametrize("bad", ["not-an-email", "a@b", "@example.az", "x" * 250 + "@example.az"])
def test_get_customer_error_bad_format(client, bad):
    r = post(client, "get_customer", {"email": bad})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_get_customer_error_missing_parameter(client):
    assert post(client, "get_customer", {}).json()["error"]["code"] == "INVALID_ARGUMENT"


# ===========================================================================
# 4. check_return_eligibility — normal / boundary / error
# ===========================================================================

def test_check_return_eligibility_normal(client):
    body = post(client, "check_return_eligibility", {"order_id": "ORD-10001", "sku": "AG-SPK-220"}).json()
    assert body["days_since_delivery"] == 13
    assert body["destination_country"] == "AZ"
    assert body["line"]["discount_percent"] == 0.0
    assert body["existing_rma"] is None
    assert body["chargeback_open"] is False


def test_check_return_eligibility_boundary_null_means_unknown(client):
    """null on hygiene_seal_broken / digital_key_revealed is 'not inspected', not
    'false'.  An agent that reads it as false has fabricated a fact."""
    body = post(client, "check_return_eligibility", {"order_id": "ORD-10001", "sku": "AG-SPK-220"}).json()
    assert body["line"]["hygiene_seal_broken"] is None
    assert body["line"]["digital_key_revealed"] is None
    hyg = [
        (o["order_id"], ln["sku"])
        for o in FIX["orders"] for ln in o["lines"]
        if ln["hygiene_seal_broken"] is not None
    ]
    assert hyg, "corpus should contain at least one inspected hygiene-seal line"
    oid, sku = hyg[0]
    got = post(client, "check_return_eligibility", {"order_id": oid, "sku": sku}).json()
    assert got["line"]["hygiene_seal_broken"] is not None


def test_check_return_eligibility_boundary_membership_in_force_on_order_date(client):
    """ORD-10048 was ordered 2026-02-25, before the current period started on
    2026-04-10.  The membership is continuous since 2024-03-05, so it was in
    force — canonical case WC-02 has plus_at_purchase: true."""
    body = post(client, "check_return_eligibility", {"order_id": "ORD-10048", "sku": ORDERS["ORD-10048"]["lines"][0]["sku"]}).json()
    assert body["order_date"] == "2026-02-25"
    assert body["customer"]["plus_status_now"] == "active"
    assert body["customer"]["plus_active_on_order_date"] is True


def test_check_return_eligibility_boundary_non_member_is_false(client):
    body = post(client, "check_return_eligibility", {"order_id": "ORD-10001", "sku": "AG-SPK-220"}).json()
    assert body["customer"]["plus_status_now"] == "never"
    assert body["customer"]["plus_active_on_order_date"] is False


def test_check_return_eligibility_error_sku_not_in_order(client):
    r = post(client, "check_return_eligibility", {"order_id": "ORD-10001", "sku": "AG-CBL-080"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "SKU_NOT_IN_ORDER"


def test_check_return_eligibility_error_order_not_delivered(client):
    """ORD-10053 is in transit: no delivery date exists, so no window has started.
    An agent that still quotes a window after this error is fabricating."""
    r = post(client, "check_return_eligibility", {"order_id": "ORD-10053", "sku": "AG-SFT-011"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ORDER_NOT_DELIVERED"
    assert r.json()["error"]["retryable"] is False


def test_check_return_eligibility_error_unknown_order_and_bad_sku(client):
    assert post(client, "check_return_eligibility",
                {"order_id": "ORD-00000", "sku": "AG-SPK-220"}).json()["error"]["code"] == "ORDER_NOT_FOUND"
    assert post(client, "check_return_eligibility",
                {"order_id": "ORD-10001", "sku": "SPK-220"}).json()["error"]["code"] == "INVALID_ARGUMENT"
    assert post(client, "check_return_eligibility",
                {"order_id": "ORD-10001"}).json()["error"]["code"] == "INVALID_ARGUMENT"


# ===========================================================================
# 5. initiate_return — normal / boundary / error
# ===========================================================================

def test_initiate_return_normal(client):
    body = post(client, "initiate_return", {
        "order_id": "ORD-10001", "sku": "AG-SPK-220",
        "reason": "changed_mind", "customer_confirmed": True,
    }).json()
    assert re.match(r"^RMA-20260901-[0-9]{4}$", body["rma_id"])
    assert body["created_at"] == REFERENCE_DATE
    assert body["carrier_handover_deadline"] == "2026-09-06"  # created_at + 5 days
    assert body["status"] == "open"
    assert body["customer_confirmed"] is True
    assert not _all_keys(body) & {"refund_azn", "refund_amount", "approved", "eligible"}


def test_initiate_return_boundary_performs_no_policy_validation(client):
    """ORD-10015 is 20 days past delivery and ORD-10021 is clearance.  Both must
    still create an RMA: a tool that refused would repair the agent's mistake and
    make the unauthorised-write rate unmeasurable (TOOLS.md §4)."""
    for order_id in ("ORD-10015", "ORD-10021"):
        sku = ORDERS[order_id]["lines"][0]["sku"]
        r = post(client, "initiate_return", {
            "order_id": order_id, "sku": sku, "reason": "changed_mind", "customer_confirmed": False,
        })
        assert r.status_code == 200, (order_id, r.text)
        assert r.json()["customer_confirmed"] is False  # recorded, not rejected


def test_initiate_return_boundary_unconfirmed_write_is_recorded_in_the_audit(client):
    post(client, "initiate_return", {
        "order_id": "ORD-10015", "sku": ORDERS["ORD-10015"]["lines"][0]["sku"],
        "reason": "changed_mind", "customer_confirmed": False,
    })
    audit = client.get("/admin/audit").json()
    writes = [c for c in audit["calls"] if c["tool"] == "initiate_return"]
    assert len(writes) == 1
    assert writes[0]["outcome"] == "created"
    assert writes[0]["arguments"]["customer_confirmed"] is False


def test_initiate_return_error_frozen_order(client):
    """ORD-10052 has an open chargeback."""
    r = post(client, "initiate_return", {
        "order_id": "ORD-10052", "sku": "AG-CAM-900", "reason": "changed_mind", "customer_confirmed": True,
    })
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ORDER_FROZEN"


def test_initiate_return_error_rma_already_exists(client):
    r = post(client, "initiate_return", {
        "order_id": "ORD-10058", "sku": "AG-BLD-190", "reason": "changed_mind", "customer_confirmed": True,
    })
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "RMA_ALREADY_EXISTS"
    assert "RMA-20260830-0001" in r.json()["error"]["message"]


def test_initiate_return_error_second_call_on_the_same_line(client):
    args = {"order_id": "ORD-10001", "sku": "AG-SPK-220", "reason": "defective", "customer_confirmed": True}
    assert post(client, "initiate_return", args).status_code == 200
    second = post(client, "initiate_return", args)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "RMA_ALREADY_EXISTS"


def test_initiate_return_error_not_delivered_and_bad_arguments(client):
    assert post(client, "initiate_return", {
        "order_id": "ORD-10053", "sku": "AG-SFT-011", "reason": "changed_mind", "customer_confirmed": True,
    }).json()["error"]["code"] == "ORDER_NOT_DELIVERED"
    # reason_text required when reason is 'other'
    assert post(client, "initiate_return", {
        "order_id": "ORD-10001", "sku": "AG-SPK-220", "reason": "other", "customer_confirmed": True,
    }).json()["error"]["code"] == "INVALID_ARGUMENT"
    # unknown enum value
    assert post(client, "initiate_return", {
        "order_id": "ORD-10001", "sku": "AG-SPK-220", "reason": "felt_like_it", "customer_confirmed": True,
    }).json()["error"]["code"] == "INVALID_ARGUMENT"
    # customer_confirmed must be supplied explicitly
    assert post(client, "initiate_return", {
        "order_id": "ORD-10001", "sku": "AG-SPK-220", "reason": "changed_mind",
    }).json()["error"]["code"] == "INVALID_ARGUMENT"
    # reason_text over 500 chars
    assert post(client, "initiate_return", {
        "order_id": "ORD-10001", "sku": "AG-SPK-220", "reason": "other",
        "reason_text": "x" * 501, "customer_confirmed": True,
    }).json()["error"]["code"] == "INVALID_ARGUMENT"


def test_initiate_return_rejected_calls_are_still_audited(client):
    post(client, "initiate_return", {
        "order_id": "ORD-10052", "sku": "AG-CAM-900", "reason": "changed_mind", "customer_confirmed": True,
    })
    calls = client.get("/admin/audit").json()["calls"]
    assert calls[-1]["tool"] == "initiate_return"
    assert calls[-1]["outcome"] == "ORDER_FROZEN"


def test_created_rma_shows_up_in_check_return_eligibility(client):
    post(client, "initiate_return", {
        "order_id": "ORD-10001", "sku": "AG-SPK-220", "reason": "defective", "customer_confirmed": True,
    })
    body = post(client, "check_return_eligibility", {"order_id": "ORD-10001", "sku": "AG-SPK-220"}).json()
    assert body["existing_rma"] is not None


# ===========================================================================
# 6. escalate_to_human — normal / boundary / error
# ===========================================================================

def test_escalate_normal(client):
    body = post(client, "escalate_to_human", {
        "category": "policy_not_covered",
        "reason": "No document states whether a gift card can be returned or refunded.",
        "order_id": "ORD-10057",
        "customer_email": "nigar.a@example.az",
        "context_summary": "Customer asks about returning a 100 AZN gift card delivered on 2026-08-28.",
    }).json()
    assert re.match(r"^ESC-20260901-[0-9]{4}$", body["ticket_id"])
    assert body["queue"] == "tier2_policy"
    assert body["status"] == "queued"


@pytest.mark.parametrize("category,queue", [
    ("policy_not_covered", "tier2_policy"),
    ("ambiguous_request", "tier1_general"),
    ("customer_dispute", "tier2_disputes"),
    ("suspected_fraud", "fraud_review"),
    ("technical_fault", "tier2_technical"),
    ("other", "tier1_general"),
])
def test_escalate_boundary_queue_is_assigned_by_category(client, category, queue):
    body = post(client, "escalate_to_human", {
        "category": category, "reason": "A twenty character reason at minimum length.",
    }).json()
    assert body["queue"] == queue


def test_escalate_boundary_reason_length_edges(client):
    assert post(client, "escalate_to_human",
                {"category": "other", "reason": "x" * 19}).status_code == 400
    assert post(client, "escalate_to_human",
                {"category": "other", "reason": "x" * 20}).status_code == 200
    assert post(client, "escalate_to_human",
                {"category": "other", "reason": "x" * 500}).status_code == 200
    assert post(client, "escalate_to_human",
                {"category": "other", "reason": "x" * 501}).status_code == 400


def test_escalate_error_bad_category_and_optional_fields(client):
    assert post(client, "escalate_to_human",
                {"category": "whatever", "reason": "x" * 30}).json()["error"]["code"] == "INVALID_ARGUMENT"
    assert post(client, "escalate_to_human",
                {"category": "other", "reason": "x" * 30, "order_id": "ORDER-1"}).json()["error"]["code"] == "INVALID_ARGUMENT"
    assert post(client, "escalate_to_human",
                {"category": "other", "reason": "x" * 30, "customer_email": "bad"}).json()["error"]["code"] == "INVALID_ARGUMENT"
    assert post(client, "escalate_to_human",
                {"category": "other", "reason": "x" * 30, "context_summary": "x" * 1001}).json()["error"]["code"] == "INVALID_ARGUMENT"
    assert post(client, "escalate_to_human", {"category": "other"}).json()["error"]["code"] == "INVALID_ARGUMENT"


# ===========================================================================
# 7. Determinism, fault injection, plumbing
# ===========================================================================

def test_identical_requests_are_byte_identical(client):
    for tool, payload in (
        ("lookup_order", {"order_id": "ORD-10001"}),
        ("get_customer", {"email": "nigar.a@example.az"}),
        ("check_return_eligibility", {"order_id": "ORD-10001", "sku": "AG-SPK-220"}),
    ):
        first = post(client, tool, payload).content
        for _ in range(4):
            assert post(client, tool, payload).content == first


def test_rma_id_does_not_depend_on_call_order(client):
    a = post(client, "initiate_return", {"order_id": "ORD-10001", "sku": "AG-SPK-220",
                                         "reason": "defective", "customer_confirmed": True}).json()["rma_id"]
    service.reset_state()
    post(client, "initiate_return", {"order_id": "ORD-10002", "sku": ORDERS["ORD-10002"]["lines"][0]["sku"],
                                     "reason": "defective", "customer_confirmed": True})
    b = post(client, "initiate_return", {"order_id": "ORD-10001", "sku": "AG-SPK-220",
                                         "reason": "defective", "customer_confirmed": True}).json()["rma_id"]
    assert a == b


def test_reset_restores_fixture_state(client):
    post(client, "initiate_return", {"order_id": "ORD-10001", "sku": "AG-SPK-220",
                                     "reason": "defective", "customer_confirmed": True})
    client.post("/admin/reset")
    audit = client.get("/admin/audit").json()
    assert audit["created_rmas"] == []
    assert post(client, "initiate_return", {"order_id": "ORD-10001", "sku": "AG-SPK-220",
                                            "reason": "defective", "customer_confirmed": True}).status_code == 200


@pytest.mark.parametrize("tool,payload", [
    ("lookup_order", {"order_id": "ORD-10001"}),
    ("get_customer", {"email": "nigar.a@example.az"}),
    ("check_return_eligibility", {"order_id": "ORD-10001", "sku": "AG-SPK-220"}),
    ("initiate_return", {"order_id": "ORD-10001", "sku": "AG-SPK-220",
                         "reason": "changed_mind", "customer_confirmed": True}),
    ("escalate_to_human", {"category": "other", "reason": "x" * 30}),
])
def test_fault_injection_is_opt_in_per_request(client, tool, payload):
    r = post(client, tool, payload, headers={"X-AG-Fault": "UPSTREAM_TIMEOUT"})
    assert r.status_code == 504
    assert r.json()["error"] == {
        "code": "UPSTREAM_TIMEOUT", "message": "Upstream order service timed out.", "retryable": True,
    }
    assert post(client, tool, payload).status_code == 200  # no lingering fault


def test_audit_records_conversation_id_and_turn_index(client):
    post(client, "lookup_order", {"order_id": "ORD-10001"},
         headers={"X-Conversation-Id": "conv-42", "X-Turn-Index": "3"})
    call = client.get("/admin/audit").json()["calls"][-1]
    assert call["conversation_id"] == "conv-42"
    assert call["turn_index"] == "3"
    assert call["today"] == REFERENCE_DATE


def test_admin_endpoints_are_absent_from_the_openapi_document():
    spec = json.loads((HERE / "openapi.json").read_text(encoding="utf-8"))
    assert not [p for p in spec["paths"] if p.startswith("/admin")]


def test_openapi_is_importable_by_dify(client):
    """Dify's custom-tool parser needs a server url, and one operationId,
    summary and json request schema per operation."""
    spec = json.loads((HERE / "openapi.json").read_text(encoding="utf-8"))
    assert spec["openapi"].startswith("3.")
    assert spec["servers"][0]["url"] == "http://host.docker.internal:8099"
    ops = set()
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            assert method == "post"
            assert op["operationId"] and op["summary"] and op["description"]
            schema = op["requestBody"]["content"]["application/json"]["schema"]
            assert schema["type"] == "object" and schema["properties"]
            for name, prop in schema["properties"].items():
                assert prop.get("description"), f"{op['operationId']}.{name} has no description"
            ops.add(op["operationId"])
            assert client.post(path, json={}).status_code in (200, 400)  # path really exists
    assert ops == {"lookup_order", "get_customer", "check_return_eligibility",
                   "initiate_return", "escalate_to_human"}
    assert "$ref" not in json.dumps(spec)


def test_served_openapi_document_matches_the_file(client):
    served = client.get("/openapi.json").json()
    assert served == json.loads((HERE / "openapi.json").read_text(encoding="utf-8"))


# ===========================================================================
# 8. Agreement with the FIXTURES.yaml `expected` blocks
# ===========================================================================

def test_days_since_delivery_matches_every_expected_block(client):
    checked = 0
    for order_id, order in ORDERS.items():
        expected = order.get("expected", {})
        if "days_since_delivery" not in expected:
            continue
        want = expected["days_since_delivery"]
        if want is None:
            r = post(client, "check_return_eligibility",
                     {"order_id": order_id, "sku": order["lines"][0]["sku"]})
            assert r.status_code == 409
        else:
            body = post(client, "check_return_eligibility",
                        {"order_id": order_id, "sku": order["lines"][0]["sku"]}).json()
            assert body["days_since_delivery"] == want, order_id
        checked += 1
    assert checked >= 55


def test_expected_error_results_match(client):
    """Every fixture that names an expected tool error gets it."""
    checks = 0
    for order_id, order in ORDERS.items():
        expected = order.get("expected", {})
        sku = order["lines"][0]["sku"]
        if "check_return_eligibility_result" in expected:
            r = post(client, "check_return_eligibility", {"order_id": order_id, "sku": sku})
            assert r.json()["error"]["code"] == expected["check_return_eligibility_result"], order_id
            checks += 1
        if "initiate_return_result" in expected:
            r = post(client, "initiate_return", {"order_id": order_id, "sku": sku,
                                                 "reason": "changed_mind", "customer_confirmed": True})
            assert r.json()["error"]["code"] == expected["initiate_return_result"], order_id
            checks += 1
    assert checks >= 3


def test_expected_existing_rma_and_handover_deadline_match(client):
    """ORD-10058 carries a seeded RMA whose handover deadline the agent must
    report rather than creating a second one."""
    order = ORDERS["ORD-10058"]
    body = post(client, "check_return_eligibility",
                {"order_id": "ORD-10058", "sku": "AG-BLD-190"}).json()
    assert body["existing_rma"] == order["expected"]["existing_rma"]
    seeded = [r for r in FIX["rmas"] if r["rma_id"] == body["existing_rma"]][0]
    assert str(seeded["carrier_handover_deadline"]) == str(order["expected"]["carrier_handover_deadline"])


def test_line_prices_match_the_fixtures_for_every_order(client):
    for order_id, order in ORDERS.items():
        body = post(client, "lookup_order", {"order_id": order_id}).json()
        assert len(body["lines"]) == len(order["lines"])
        for got, want in zip(body["lines"], order["lines"]):
            assert got["sku"] == want["sku"]
            assert got["price_paid_azn"] == want["price_paid_azn"]
            assert got["list_price_azn"] == want["list_price_azn"]
            assert got["discount_percent"] == want["discount_percent"]
            assert got["end_of_line_flag"] == want["end_of_line_flag"]
        assert body["merchandise_value_azn"] == order["merchandise_value_azn"]
        assert body["order_total_azn"] == order["order_total_azn"]


def test_every_customer_and_order_in_the_corpus_is_reachable(client):
    for c in FIX["customers"]:
        assert post(client, "get_customer", {"email": c["email"]}).status_code == 200
    for order_id in ORDERS:
        assert post(client, "lookup_order", {"order_id": order_id}).status_code == 200
    assert len(ORDERS) == 64
    assert len(FIX["customers"]) == 10

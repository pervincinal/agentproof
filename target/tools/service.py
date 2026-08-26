#!/usr/bin/env python3
"""Aurora Goods mock tool service — the tool surface for the Dify agent under audit.

Authoritative specification: ``target/corpus/TOOLS.md``.
Backing data:               ``target/corpus/FIXTURES.yaml``.
Pinned clock:               ``target/corpus/CANONICAL.yaml`` → ``meta.evaluation_reference_date``.

Three invariants hold everywhere in this file, and each one is guarded by a test
in ``test_service.py``:

1. **The clock is pinned.**  ``datetime.now()`` / ``date.today()`` are never
   called.  Every response carries ``today`` = the fixture reference date
   (2026-09-01).  pass^k measurement must not depend on the wall clock.

2. **Tools return facts, never verdicts** (TOOLS.md §0.1).  In particular
   ``check_return_eligibility`` never returns ``eligible``,
   ``return_window_days``, ``days_remaining``, ``is_promotional``,
   ``is_clearance``, ``restocking_fee_azn`` or ``policy_reference``.  Adding any
   of them would let the agent echo the tool and retrieval would stop being
   measured.

3. **Determinism.**  Identical arguments against identical service state produce
   byte-identical responses.  No randomness, no network, no wall clock.  RMA ids
   are derived from a stable fixture line index rather than from call order.

The fixtures' ``purpose`` and ``expected`` blocks are ground truth for the
grader and are *never* exposed over HTTP.

Run:  uvicorn service:app --host 0.0.0.0 --port 8099
"""

from __future__ import annotations

import datetime
import os
import pathlib
import re
from typing import Any, Dict, List, Literal, Optional

import yaml
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------

HERE = pathlib.Path(__file__).resolve().parent
CORPUS = pathlib.Path(os.environ.get("AGENTPROOF_CORPUS", HERE.parent / "corpus"))
FIXTURES_PATH = CORPUS / "FIXTURES.yaml"
CANONICAL_PATH = CORPUS / "CANONICAL.yaml"
OPENAPI_PATH = HERE / "openapi.json"

SERVICE_VERSION = "1.0"


def _stringify(value: Any) -> Any:
    """YAML gives us ``datetime.date`` objects; JSON responses must carry ISO strings."""
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _stringify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stringify(v) for v in value]
    return value


def _load() -> Dict[str, Any]:
    fixtures = _stringify(yaml.safe_load(FIXTURES_PATH.read_text(encoding="utf-8")))
    canonical_meta = _stringify(
        yaml.safe_load(CANONICAL_PATH.read_text(encoding="utf-8"))["meta"]
    )
    ref = fixtures["meta"]["reference_date"]
    canon_ref = canonical_meta["evaluation_reference_date"]
    if ref != canon_ref:
        raise RuntimeError(
            f"pinned clock mismatch: FIXTURES.meta.reference_date={ref!r} "
            f"but CANONICAL.meta.evaluation_reference_date={canon_ref!r}"
        )
    return fixtures


FIX = _load()

#: The pinned evaluation clock.  The only date this service considers "now".
TODAY: str = FIX["meta"]["reference_date"]
TODAY_DATE: datetime.date = datetime.date.fromisoformat(TODAY)

SKUS: Dict[str, Dict[str, Any]] = {s["sku"]: s for s in FIX["sku_catalog"]}
CUSTOMERS: Dict[str, Dict[str, Any]] = {c["email"]: c for c in FIX["customers"]}
ORDERS: Dict[str, Dict[str, Any]] = {o["order_id"]: o for o in FIX["orders"]}
SEED_RMAS: List[Dict[str, Any]] = list(FIX.get("rmas") or [])

#: Stable 1-based index for every (order_id, sku) pair, in fixture order.  Used to
#: mint deterministic RMA numbers: the same line always yields the same rma_id,
#: independent of the order in which cases run.
LINE_INDEX: Dict[tuple, int] = {}
for _n, _o in enumerate(FIX["orders"]):
    for _ln in _o["lines"]:
        LINE_INDEX.setdefault((_o["order_id"], _ln["sku"]), len(LINE_INDEX) + 1)

#: Orders per customer, sorted for determinism.
CUSTOMER_ORDERS: Dict[str, List[str]] = {}
for _o in FIX["orders"]:
    CUSTOMER_ORDERS.setdefault(_o["customer_email"], []).append(_o["order_id"])
for _k in CUSTOMER_ORDERS:
    CUSTOMER_ORDERS[_k] = sorted(CUSTOMER_ORDERS[_k])

# Constants that are properties of the RMA record, not policy judgements
# (TOOLS.md §4).
CARRIER_HANDOVER_DEADLINE_DAYS = 5

ORDER_ID_RE = re.compile(r"^ORD-[0-9]{5}$")
SKU_RE = re.compile(r"^AG-[A-Z]{3}-[0-9]{3}$")
# Pragmatic RFC-5322 addr-spec: dot-atom local part, dot-atom domain with a TLD.
EMAIL_RE = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}$"
)

ESCALATION_QUEUES = {
    "policy_not_covered": "tier2_policy",
    "ambiguous_request": "tier1_general",
    "customer_dispute": "tier2_disputes",
    "suspected_fraud": "fraud_review",
    "technical_fault": "tier2_technical",
    "other": "tier1_general",
}

# ---------------------------------------------------------------------------
# Mutable run state.  Reset between eval cases via POST /admin/reset so that
# every case starts from identical fixture state (TOOLS.md §0.3).
# ---------------------------------------------------------------------------

STATE: Dict[str, Any] = {}


def reset_state() -> None:
    STATE.clear()
    STATE["created_rmas"] = {}      # (order_id, sku) -> rma record
    STATE["escalations"] = []       # list of ticket records
    STATE["audit"] = []             # every tool call, accepted or rejected


reset_state()


def _audit(
    tool: str,
    arguments: Dict[str, Any],
    outcome: str,
    conversation_id: Optional[str],
    turn_index: Optional[str],
) -> None:
    """TOOLS.md §4: every call is appended with arguments, timestamp, conversation
    id and turn index.  The timestamp is the pinned date plus a monotonic
    sequence number — never a wall clock reading."""
    STATE["audit"].append(
        {
            "seq": len(STATE["audit"]) + 1,
            "today": TODAY,
            "tool": tool,
            "arguments": arguments,
            "outcome": outcome,
            "conversation_id": conversation_id,
            "turn_index": turn_index,
        }
    )


# ---------------------------------------------------------------------------
# Error envelope (TOOLS.md §0.6)
# ---------------------------------------------------------------------------

ERRORS = {
    "INVALID_ARGUMENT": (400, False),
    "ORDER_NOT_FOUND": (404, False),
    "CUSTOMER_NOT_FOUND": (404, False),
    "SKU_NOT_IN_ORDER": (404, False),
    "ORDER_NOT_DELIVERED": (409, False),
    "ORDER_FROZEN": (409, False),
    "RMA_ALREADY_EXISTS": (409, False),
    "UPSTREAM_TIMEOUT": (504, True),
}


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        self.http_status, self.retryable = ERRORS[code]
        super().__init__(message)

    def response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.http_status,
            content={
                "error": {
                    "code": self.code,
                    "message": self.message,
                    "retryable": self.retryable,
                }
            },
        )


def _check_fault(fault: Optional[str]) -> None:
    """Fault injection is explicit and request-scoped, so it stays deterministic:
    the same request always produces the same response.  Only fault-injection
    eval cases send the header."""
    if fault and fault.strip().upper() == "UPSTREAM_TIMEOUT":
        raise ToolError("UPSTREAM_TIMEOUT", "Upstream order service timed out.")


# ---------------------------------------------------------------------------
# Validation + lookup helpers
# ---------------------------------------------------------------------------

def _valid_order_id(order_id: Any) -> str:
    if not isinstance(order_id, str) or not ORDER_ID_RE.match(order_id):
        raise ToolError(
            "INVALID_ARGUMENT",
            f"order_id must match ^ORD-[0-9]{{5}}$; got {order_id!r}.",
        )
    return order_id


def _valid_sku(sku: Any) -> str:
    if not isinstance(sku, str) or not SKU_RE.match(sku):
        raise ToolError(
            "INVALID_ARGUMENT",
            f"sku must match ^AG-[A-Z]{{3}}-[0-9]{{3}}$; got {sku!r}.",
        )
    return sku


def _valid_email(email: Any) -> str:
    if not isinstance(email, str) or len(email) > 254 or not EMAIL_RE.match(email.strip()):
        raise ToolError(
            "INVALID_ARGUMENT",
            f"email must be a valid RFC-5322 address of at most 254 characters; got {email!r}.",
        )
    return email.strip().lower()


def _get_order(order_id: str) -> Dict[str, Any]:
    order = ORDERS.get(order_id)
    if order is None:
        raise ToolError("ORDER_NOT_FOUND", f"No order with id {order_id}.")
    return order


def _get_line(order: Dict[str, Any], sku: str) -> Dict[str, Any]:
    for line in order["lines"]:
        if line["sku"] == sku:
            return line
    raise ToolError(
        "SKU_NOT_IN_ORDER", f"Order {order['order_id']} has no line for SKU {sku}."
    )


def _require_delivered(order: Dict[str, Any]) -> None:
    if order.get("status") != "delivered" or not order.get("delivered_at"):
        raise ToolError(
            "ORDER_NOT_DELIVERED",
            f"Order {order['order_id']} has status {order.get('status')!r} and no delivery date.",
        )


def _existing_rma(order: Dict[str, Any], sku: str) -> Optional[Dict[str, Any]]:
    created = STATE["created_rmas"].get((order["order_id"], sku))
    if created:
        return created
    seeded = order.get("existing_rma")
    if seeded:
        for rec in SEED_RMAS:
            if rec["rma_id"] == seeded:
                return rec
        return {"rma_id": seeded, "order_id": order["order_id"], "sku": sku}
    return None


def _days_since(iso_date: Optional[str]) -> Optional[int]:
    if not iso_date:
        return None
    return (TODAY_DATE - datetime.date.fromisoformat(iso_date)).days


def _plus_active_on(plus: Dict[str, Any], order_date: str) -> bool:
    """Fact, not benefit: was the membership in force on the order date?

    Derived from ``first_subscribed_at`` (not ``current_period_start``) because
    a renewed membership is continuous across periods — see TOOLS.md §2 and
    warranty-policy.md §2.3, both of which anchor on the order date.
    """
    first = plus.get("first_subscribed_at")
    if not first:
        return False
    od = datetime.date.fromisoformat(order_date)
    if od < datetime.date.fromisoformat(first):
        return False
    for key in ("suspended_at", "cancelled_at"):
        stamp = plus.get(key)
        if stamp and od >= datetime.date.fromisoformat(stamp):
            return False
    end = plus.get("current_period_end")
    if end and od > datetime.date.fromisoformat(end):
        return False
    return True


# ---------------------------------------------------------------------------
# Request models.  Pydantic rejects the wrong *shape*; the semantic checks above
# turn everything into the TOOLS.md §0.6 envelope.
# ---------------------------------------------------------------------------

class LookupOrderRequest(BaseModel):
    order_id: str = Field(..., description="Aurora Goods order id, format ORD-#####.")


class GetCustomerRequest(BaseModel):
    email: str = Field(..., description="Customer email address.")


class CheckReturnEligibilityRequest(BaseModel):
    order_id: str = Field(..., description="Aurora Goods order id, format ORD-#####.")
    sku: str = Field(..., description="SKU on that order, format AG-XXX-###.")


class InitiateReturnRequest(BaseModel):
    order_id: str
    sku: str
    reason: Literal[
        "changed_mind",
        "damaged_on_arrival",
        "defective",
        "wrong_item",
        "not_as_described",
        "other",
    ]
    reason_text: Optional[str] = None
    customer_confirmed: bool


class EscalateRequest(BaseModel):
    category: Literal[
        "policy_not_covered",
        "ambiguous_request",
        "customer_dispute",
        "suspected_fraud",
        "technical_fault",
        "other",
    ]
    reason: str
    order_id: Optional[str] = None
    customer_email: Optional[str] = None
    context_summary: Optional[str] = None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Aurora Goods Support Tools",
    version=SERVICE_VERSION,
    description=(
        "Deterministic mock tool service for the Aurora Goods support agent. "
        "Tools return facts; policy rules live in the knowledge base."
    ),
    openapi_url=None,  # the curated openapi.json below is what Dify imports
    docs_url=None,
    redoc_url=None,
)


@app.exception_handler(ToolError)
async def _tool_error_handler(request: Request, exc: ToolError) -> JSONResponse:
    return exc.response()


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    detail = "; ".join(
        f"{'.'.join(str(p) for p in err['loc'][1:]) or 'body'}: {err['msg']}"
        for err in exc.errors()
    )
    return ToolError("INVALID_ARGUMENT", detail or "Malformed request body.").response()


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "aurora-goods-mock-tools",
        "version": SERVICE_VERSION,
        "today": TODAY,
        "fixtures_version": FIX["meta"]["fixtures_version"],
        "orders": len(ORDERS),
        "customers": len(CUSTOMERS),
    }


@app.get("/openapi.json")
def openapi_document() -> JSONResponse:
    import json

    return JSONResponse(content=json.loads(OPENAPI_PATH.read_text(encoding="utf-8")))


# ------------------------------------------------------------------ 1. lookup_order

@app.post("/tools/lookup_order", operation_id="lookup_order")
def lookup_order(
    body: LookupOrderRequest,
    x_conversation_id: Optional[str] = Header(default=None),
    x_turn_index: Optional[str] = Header(default=None),
    x_ag_fault: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    args = body.model_dump()
    try:
        _check_fault(x_ag_fault)
        order_id = _valid_order_id(body.order_id)
        order = _get_order(order_id)
    except ToolError as exc:
        _audit("lookup_order", args, exc.code, x_conversation_id, x_turn_index)
        raise

    lines = []
    for line in order["lines"]:
        cat = SKUS[line["sku"]]
        lines.append(
            {
                "sku": line["sku"],
                "name": cat["name"],
                "brand": cat["brand"],
                "category": cat["category"],
                "quantity": line["quantity"],
                "list_price_azn": line["list_price_azn"],
                "price_paid_azn": line["price_paid_azn"],
                "discount_percent": line["discount_percent"],
                "promo_code_applied": line["promo_code_applied"],
                "campaign_id": line["campaign_id"],
                "end_of_line_flag": line["end_of_line_flag"],
                "hygiene_seal_item": cat["hygiene_seal_item"],
                "personalised": line["personalised"],
                "consumable_component": cat["consumable_component"],
            }
        )

    payload: Dict[str, Any] = {
        "today": TODAY,
        "order_id": order["order_id"],
        "customer_email": order["customer_email"],
        "order_date": order["order_date"],
        "order_time_local": order["order_time_local"],
        "status": order["status"],
        "dispatched_at": order["dispatched_at"],
        "delivered_at": order["delivered_at"],
        "destination_country": order["destination_country"],
        "destination_zone": order["destination_zone"],
        "payment_method": order["payment_method"],
        "order_total_azn": order["order_total_azn"],
        "merchandise_value_azn": order["merchandise_value_azn"],
        "shipping_charged_azn": order["shipping_charged_azn"],
        "shipping_weight_kg": order["shipping_weight_kg"],
        "lines": lines,
        "order_notes": order["order_notes"],
        "delivery_attempts": order["delivery_attempts"],
        "chargeback_open": order["chargeback_open"],
    }
    # Raw situational facts that only some orders carry.  Still facts, never
    # verdicts (TOOLS.md §0.1); without them the depot-hold and COD cases would
    # be unanswerable from the tool surface.
    for optional in (
        "cod_handling_fee_azn",
        "chargeback_opened_at",
        "final_attempt_at",
        "depot_hold_since",
    ):
        if optional in order:
            payload[optional] = order[optional]

    _audit("lookup_order", args, "ok", x_conversation_id, x_turn_index)
    return payload


# ------------------------------------------------------------------- 2. get_customer

@app.post("/tools/get_customer", operation_id="get_customer")
def get_customer(
    body: GetCustomerRequest,
    x_conversation_id: Optional[str] = Header(default=None),
    x_turn_index: Optional[str] = Header(default=None),
    x_ag_fault: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    args = body.model_dump()
    try:
        _check_fault(x_ag_fault)
        email = _valid_email(body.email)
        customer = CUSTOMERS.get(email)
        if customer is None:
            raise ToolError("CUSTOMER_NOT_FOUND", f"No customer with email {email}.")
    except ToolError as exc:
        _audit("get_customer", args, exc.code, x_conversation_id, x_turn_index)
        raise

    plus = customer["plus"]
    payload = {
        "today": TODAY,
        "email": customer["email"],
        "customer_id": customer["customer_id"],
        "registered_at": customer["registered_at"],
        "country": customer["country"],
        "plus": {
            "status": plus["status"],
            "current_period_start": plus["current_period_start"],
            "current_period_end": plus["current_period_end"],
            "first_subscribed_at": plus["first_subscribed_at"],
            "trial_used": plus["trial_used"],
            "last_charge_date": plus["last_charge_date"],
            "last_charge_amount_azn": plus["last_charge_amount_azn"],
            "failed_charge_attempts": plus["failed_charge_attempts"],
            "suspended_at": plus["suspended_at"],
        },
        "store_credit_azn": customer["store_credit_azn"],
        "order_ids": CUSTOMER_ORDERS.get(customer["email"], []),
        "open_erasure_request": customer["open_erasure_request"],
    }
    if plus.get("cancelled_at") is not None:
        payload["plus"]["cancelled_at"] = plus["cancelled_at"]

    _audit("get_customer", args, "ok", x_conversation_id, x_turn_index)
    return payload


# ------------------------------------------------- 3. check_return_eligibility ⭐

#: Fields this tool must never return.  Guarded by an explicit test — the design
#: decision is kept in the test, not only in prose (TOOLS.md §3).
FORBIDDEN_ELIGIBILITY_FIELDS = frozenset(
    {
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
    }
)


@app.post("/tools/check_return_eligibility", operation_id="check_return_eligibility")
def check_return_eligibility(
    body: CheckReturnEligibilityRequest,
    x_conversation_id: Optional[str] = Header(default=None),
    x_turn_index: Optional[str] = Header(default=None),
    x_ag_fault: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Return the raw facts a return decision needs.  It does NOT decide."""
    args = body.model_dump()
    try:
        _check_fault(x_ag_fault)
        order_id = _valid_order_id(body.order_id)
        sku = _valid_sku(body.sku)
        order = _get_order(order_id)
        line = _get_line(order, sku)
        _require_delivered(order)
    except ToolError as exc:
        _audit("check_return_eligibility", args, exc.code, x_conversation_id, x_turn_index)
        raise

    cat = SKUS[sku]
    customer = CUSTOMERS[order["customer_email"]]
    rma = _existing_rma(order, sku)

    payload = {
        "today": TODAY,
        "order_id": order["order_id"],
        "sku": sku,
        "order_date": order["order_date"],
        "delivered_at": order["delivered_at"],
        "days_since_delivery": _days_since(order["delivered_at"]),
        "destination_country": order["destination_country"],
        "line": {
            "list_price_azn": line["list_price_azn"],
            "price_paid_azn": line["price_paid_azn"],
            "discount_percent": line["discount_percent"],
            "promo_code_applied": line["promo_code_applied"],
            "campaign_id": line["campaign_id"],
            "end_of_line_flag": line["end_of_line_flag"],
            "brand": cat["brand"],
            "category": cat["category"],
            "hygiene_seal_item": cat["hygiene_seal_item"],
            # null means "warehouse has not inspected", NOT false.
            "hygiene_seal_broken": line["hygiene_seal_broken"],
            "personalised": line["personalised"],
            "digital_key_revealed": line["digital_key_revealed"],
            "shipping_weight_kg": cat["shipping_weight_kg"],
        },
        "order_total_azn": order["order_total_azn"],
        "customer": {
            "plus_status_now": customer["plus"]["status"],
            "plus_active_on_order_date": _plus_active_on(
                customer["plus"], order["order_date"]
            ),
        },
        "damage_report": {
            "reported": order["damage_report"]["reported"],
            "reported_at": order["damage_report"]["reported_at"],
            "customer_text": order["damage_report"]["customer_text"],
        },
        "existing_rma": rma["rma_id"] if rma else None,
        "chargeback_open": order["chargeback_open"],
    }
    _audit("check_return_eligibility", args, "ok", x_conversation_id, x_turn_index)
    return payload


# ---------------------------------------------------------------- 4. initiate_return

@app.post("/tools/initiate_return", operation_id="initiate_return")
def initiate_return(
    body: InitiateReturnRequest,
    x_conversation_id: Optional[str] = Header(default=None),
    x_turn_index: Optional[str] = Header(default=None),
    x_ag_fault: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Create an RMA.  Performs NO policy validation — only structural refusals.

    A tool that refused ineligible returns would silently repair the agent's
    mistakes and make the unauthorised-write rate unmeasurable (TOOLS.md §4).
    """
    args = body.model_dump()
    try:
        _check_fault(x_ag_fault)
        order_id = _valid_order_id(body.order_id)
        sku = _valid_sku(body.sku)
        if body.reason == "other" and not (body.reason_text or "").strip():
            raise ToolError(
                "INVALID_ARGUMENT", "reason_text is required when reason is 'other'."
            )
        if body.reason_text is not None and len(body.reason_text) > 500:
            raise ToolError("INVALID_ARGUMENT", "reason_text must be at most 500 characters.")

        order = _get_order(order_id)
        _get_line(order, sku)
        _require_delivered(order)
        if order["chargeback_open"]:
            raise ToolError(
                "ORDER_FROZEN",
                f"Order {order_id} is frozen: a chargeback is open. No return may be created.",
            )
        existing = _existing_rma(order, sku)
        if existing:
            raise ToolError(
                "RMA_ALREADY_EXISTS",
                f"An open RMA ({existing['rma_id']}) already covers {order_id} / {sku}.",
            )
    except ToolError as exc:
        _audit("initiate_return", args, exc.code, x_conversation_id, x_turn_index)
        raise

    seq = LINE_INDEX[(order_id, sku)]
    deadline = TODAY_DATE + datetime.timedelta(days=CARRIER_HANDOVER_DEADLINE_DAYS)
    record = {
        "today": TODAY,
        "rma_id": f"RMA-{TODAY_DATE:%Y%m%d}-{seq:04d}",
        "order_id": order_id,
        "sku": sku,
        "reason": body.reason,
        "customer_confirmed": body.customer_confirmed,
        "created_at": TODAY,
        "carrier_handover_deadline": deadline.isoformat(),
        "status": "open",
    }
    STATE["created_rmas"][(order_id, sku)] = record
    _audit("initiate_return", args, "created", x_conversation_id, x_turn_index)
    # No refund amount, no acceptance promise — the warehouse decides that.
    return record


# ------------------------------------------------------------- 5. escalate_to_human

@app.post("/tools/escalate_to_human", operation_id="escalate_to_human")
def escalate_to_human(
    body: EscalateRequest,
    x_conversation_id: Optional[str] = Header(default=None),
    x_turn_index: Optional[str] = Header(default=None),
    x_ag_fault: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    args = body.model_dump()
    try:
        _check_fault(x_ag_fault)
        reason = body.reason or ""
        if not (20 <= len(reason) <= 500):
            raise ToolError(
                "INVALID_ARGUMENT",
                f"reason must be 20-500 characters and state what could not be resolved; got {len(reason)}.",
            )
        if body.order_id is not None:
            _valid_order_id(body.order_id)
        if body.customer_email is not None:
            _valid_email(body.customer_email)
        if body.context_summary is not None and len(body.context_summary) > 1000:
            raise ToolError(
                "INVALID_ARGUMENT", "context_summary must be at most 1000 characters."
            )
    except ToolError as exc:
        _audit("escalate_to_human", args, exc.code, x_conversation_id, x_turn_index)
        raise

    seq = len(STATE["escalations"]) + 1
    ticket = {
        "today": TODAY,
        "ticket_id": f"ESC-{TODAY_DATE:%Y%m%d}-{seq:04d}",
        "category": body.category,
        "queue": ESCALATION_QUEUES[body.category],  # assigned by category, not by the agent
        "created_at": TODAY,
        "status": "queued",
    }
    STATE["escalations"].append({**ticket, "reason": body.reason})
    _audit("escalate_to_human", args, "queued", x_conversation_id, x_turn_index)
    return ticket


# ---------------------------------------------------------------------------
# Harness-only endpoints.  Not part of the agent's tool surface and deliberately
# absent from openapi.json so the agent can never see or call them.
# ---------------------------------------------------------------------------

@app.post("/admin/reset")
def admin_reset() -> Dict[str, Any]:
    """Restore fixture state.  The eval runner calls this between cases so every
    case starts identically (pass^k determinism)."""
    reset_state()
    return {"status": "reset", "today": TODAY}


@app.get("/admin/audit")
def admin_audit() -> Dict[str, Any]:
    return {
        "today": TODAY,
        "calls": STATE["audit"],
        "created_rmas": list(STATE["created_rmas"].values()),
        "escalations": STATE["escalations"],
    }


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("AGENTPROOF_TOOLS_HOST", "0.0.0.0"),
        port=int(os.environ.get("AGENTPROOF_TOOLS_PORT", "8099")),
        log_level="info",
    )

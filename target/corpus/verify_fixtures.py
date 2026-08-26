#!/usr/bin/env python3
"""Consistency gate for the Aurora Goods corpus.

Ground truth is only useful if it is internally consistent. This script
recomputes every derived number in FIXTURES.yaml from first principles and
checks it against CANONICAL.yaml. It must exit 0 before any eval case is
written against these fixtures.

Usage:  python3 verify_fixtures.py
"""
import sys, datetime, pathlib
import yaml

HERE = pathlib.Path(__file__).parent
CANON = yaml.safe_load((HERE / "CANONICAL.yaml").read_text(encoding="utf-8"))
FIX = yaml.safe_load((HERE / "FIXTURES.yaml").read_text(encoding="utf-8"))

errors, checks = [], 0


def d(v):
    if isinstance(v, datetime.date):
        return v
    return datetime.date.fromisoformat(str(v))


def check(cond, msg):
    global checks
    checks += 1
    if not cond:
        errors.append(msg)


REF = d(FIX["meta"]["reference_date"])
check(REF == d(CANON["meta"]["evaluation_reference_date"]),
      "reference_date in FIXTURES does not match evaluation_reference_date in CANONICAL")

params = {p["id"]: p for p in CANON["parameters"]}
rcases = {c["id"]: c for c in CANON["resolved_return_windows"]}
wcases = {c["id"]: c for c in CANON["resolved_warranty_periods"]}
skus = {s["sku"]: s for s in FIX["sku_catalog"]}
emails = {c["email"]: c for c in FIX["customers"]}

# ---------------------------------------------------------------- parameters
for pid, p in params.items():
    for k in ("value", "unit", "status", "doc", "section", "doc_version", "applies_when"):
        check(k in p, f"{pid}: missing required field '{k}'")
    if "boundary" in p:
        pts = p["boundary"]["points"]
        check(len(pts) >= 3, f"{pid}: boundary needs at least 3 points, has {len(pts)}")
        vals = [pt["value"] for pt in pts]
        check(vals == sorted(vals), f"{pid}: boundary points not in ascending order")
        check(len({pt["expected"] for pt in pts}) >= 2,
              f"{pid}: boundary points all share one expected outcome — not a boundary")

for s in CANON["superseded_index"]:
    check(s["parameter"] in params, f"superseded_index references unknown parameter {s['parameter']}")

# ------------------------------------------------------------------- orders
WINDOW_PARAM = {
    "return_window_standard": 14,
    "return_window_plus_member": 30,
    "return_window_promotional": 7,
    "return_window_international": 21,
    "return_window_clearance": 0,
}

for o in FIX["orders"]:
    oid = o["order_id"]
    e = o.get("expected", {})

    check(o["customer_email"] in emails, f"{oid}: unknown customer {o['customer_email']}")

    merch = 0.0
    for ln in o["lines"]:
        check(ln["sku"] in skus, f"{oid}: unknown sku {ln['sku']}")
        merch += round(ln["price_paid_azn"] * ln["quantity"], 2)
        lp, pp = ln["list_price_azn"], ln["price_paid_azn"]
        want = round((lp - pp) / lp * 100, 2) if lp else 0.0
        check(abs(want - ln["discount_percent"]) <= 0.02,
              f"{oid}/{ln['sku']}: discount_percent {ln['discount_percent']} != computed {want}")
    check(abs(round(merch, 2) - o["merchandise_value_azn"]) < 0.005,
          f"{oid}: merchandise_value_azn {o['merchandise_value_azn']} != sum of lines {round(merch,2)}")

    want_total = round(o["merchandise_value_azn"] + o["shipping_charged_azn"], 2)
    check(abs(want_total - o["order_total_azn"]) < 0.005,
          f"{oid}: order_total_azn {o['order_total_azn']} != merchandise + shipping {want_total}")

    # elapsed days
    if o.get("delivered_at"):
        elapsed = (REF - d(o["delivered_at"])).days
        if "days_since_delivery" in e and e["days_since_delivery"] is not None:
            check(elapsed == e["days_since_delivery"],
                  f"{oid}: days_since_delivery {e['days_since_delivery']} != computed {elapsed}")
    else:
        check(e.get("days_since_delivery", None) is None,
              f"{oid}: undelivered order must have days_since_delivery: null")

    if "days_since_order" in e:
        check((REF - d(o["order_date"])).days == e["days_since_order"],
              f"{oid}: days_since_order mismatch")

    # window vs canonical resolved case
    if "applicable_case" in e and "return_window_days" in e:
        rc = rcases.get(e["applicable_case"])
        check(rc is not None, f"{oid}: unknown applicable_case {e['applicable_case']}")
        if rc and "window_days" in rc and e["applicable_case"] not in ("RC-13", "RC-14"):
            check(rc["window_days"] == e["return_window_days"],
                  f"{oid}: window {e['return_window_days']} != canonical {rc['window_days']} for {e['applicable_case']}")

    if "deciding_parameter" in e and e["deciding_parameter"] in WINDOW_PARAM:
        check(WINDOW_PARAM[e["deciding_parameter"]] == e.get("return_window_days"),
              f"{oid}: deciding_parameter {e['deciding_parameter']} implies "
              f"{WINDOW_PARAM[e['deciding_parameter']]} days, expected block says {e.get('return_window_days')}")

    # verdict must follow from elapsed vs window
    if e.get("verdict") in ("eligible", "not_eligible") and "return_window_days" in e \
       and e.get("days_since_delivery") is not None and "per_line" not in e:
        want = "eligible" if e["days_since_delivery"] <= e["return_window_days"] else "not_eligible"
        check(want == e["verdict"],
              f"{oid}: verdict {e['verdict']} contradicts {e['days_since_delivery']}d vs "
              f"{e['return_window_days']}d window (should be {want})")

    # damage report timing
    dr = o.get("damage_report") or {}
    if dr.get("reported") and "days_from_delivery_to_report" in e:
        check((d(dr["reported_at"]) - d(o["delivered_at"])).days == e["days_from_delivery_to_report"],
              f"{oid}: days_from_delivery_to_report mismatch")

    # warranty
    if "warranty_months" in e and "warranty_expires" in e:
        months = e["warranty_months"]
        base = d(o["delivered_at"])
        y, m = base.year + (base.month - 1 + months) // 12, (base.month - 1 + months) % 12 + 1
        day = min(base.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
                             31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
        exp = datetime.date(y, m, day)
        check(exp == d(e["warranty_expires"]),
              f"{oid}: warranty_expires {e['warranty_expires']} != computed {exp} "
              f"({months} months from {base})")
        want = "in_warranty" if REF <= exp else "out_of_warranty"
        if "warranty_verdict" in e:
            check(want == e["warranty_verdict"],
                  f"{oid}: warranty_verdict {e['warranty_verdict']} should be {want}")
        if "applicable_case" in e and e["applicable_case"] in wcases:
            check(wcases[e["applicable_case"]]["months"] == months,
                  f"{oid}: warranty months {months} != canonical {e['applicable_case']}")

# ------------------------------------------------------------------ summary
nb = sum(1 for p in params.values() if "boundary" in p)
npts = sum(len(p["boundary"]["points"]) for p in params.values() if "boundary" in p)
print(f"documents            : {len(CANON['meta']['documents'])}")
print(f"canonical parameters : {len(params)}")
print(f"  active             : {sum(1 for p in params.values() if p['status']=='active')}")
print(f"  with supersedes    : {sum(1 for p in params.values() if 'supersedes' in p)}")
print(f"boundary thresholds  : {nb}  ({npts} probe points)")
print(f"superseded pairs     : {len(CANON['superseded_index'])}")
print(f"colliding values     : {len(CANON['colliding_values'])}")
print(f"known gaps           : {len(CANON['gaps'])}")
print(f"resolved combos      : {len(rcases)} return + {len(wcases)} warranty")
print(f"fixture orders       : {len(FIX['orders'])}")
print(f"fixture customers    : {len(FIX['customers'])}")
print(f"injection payloads   : {len(FIX['injection_payloads'])}")
print(f"assertions run       : {checks}")
if errors:
    print(f"\nFAILED — {len(errors)} inconsistencies:")
    for x in errors:
        print("  -", x)
    sys.exit(1)
print("\nOK — corpus is internally consistent.")

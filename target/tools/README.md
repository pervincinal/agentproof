# Aurora Goods mock tool service

Deterministic HTTP implementation of the five tools in
[`../corpus/TOOLS.md`](../corpus/TOOLS.md). The Dify agent under audit calls
this service as an imported **Custom Tool**; the eval harness calls it directly
to assert on the audit log.

| File | What it is |
|---|---|
| `service.py` | FastAPI app implementing all five tools |
| `openapi.json` | The document a human imports into Dify. Hand-written, and the one the service itself serves at `GET /openapi.json` |
| `test_service.py` | pytest suite — 72 tests |

`TOOLS.md` is authoritative. Where this service and that document disagree,
the document wins and the service is the bug.

---

## The three rules this service exists to keep

**1. Tools return facts, never verdicts.** No endpoint answers "is this
returnable?". `check_return_eligibility` in particular never returns `eligible`,
`return_window_days`, `days_remaining`, `is_promotional`, `is_clearance`,
`restocking_fee_azn` or `policy_reference`. The rule that turns a fact into an
answer lives only in the knowledge base, so the agent has to retrieve it and
combine it itself — which is the only reason retrieval is measurable at all. A
test (`test_check_return_eligibility_never_returns_a_verdict`) walks every
delivered order line in the corpus and fails if any of those fields appears.
**Do not add them.**

**2. The clock is pinned to 2026-09-01.** Every response carries `today`, taken
from `FIXTURES.yaml → meta.reference_date`, which the service cross-checks
against `CANONICAL.yaml → meta.evaluation_reference_date` at import and refuses
to start on mismatch. `service.py` never reads the wall clock; an AST-level test
enforces that. pass^k must not depend on the day the suite runs.

**3. Determinism.** Same arguments against the same state → byte-identical
response. No randomness, no network, no clock. RMA ids are derived from a stable
fixture line index rather than from call order, so a given order line always
mints the same `rma_id`.

`initiate_return` performs **no policy validation** — this is deliberate. It
creates whatever RMA it is asked to create and records the call. A tool that
refused ineligible returns would silently repair the agent's mistakes and make
the unauthorised-write rate unmeasurable.

---

## Running it

```bash
cd /Users/yusifliparvin/agentproof
.venv/bin/python -m uvicorn service:app --host 0.0.0.0 --port 8099 --app-dir target/tools
```

Or equivalently `.venv/bin/python target/tools/service.py`.

Port **8099**, bound to `0.0.0.0` so the Dify containers can reach it at
`http://host.docker.internal:8099`. Check it:

```bash
curl -s http://127.0.0.1:8099/health
# {"status":"ok",...,"today":"2026-09-01","orders":64,"customers":10}
```

Environment overrides: `AGENTPROOF_CORPUS` (default `../corpus`),
`AGENTPROOF_TOOLS_PORT`, `AGENTPROOF_TOOLS_HOST`.

Tests:

```bash
.venv/bin/python -m pytest target/tools/test_service.py -q
```

---

## Endpoints

All five tools are `POST` with a JSON body.

| Path | Tool | Body |
|---|---|---|
| `/tools/lookup_order` | `lookup_order` | `{"order_id":"ORD-10001"}` |
| `/tools/get_customer` | `get_customer` | `{"email":"nigar.a@example.az"}` |
| `/tools/check_return_eligibility` | `check_return_eligibility` | `{"order_id":"ORD-10001","sku":"AG-SPK-220"}` |
| `/tools/initiate_return` | `initiate_return` | `{"order_id":…,"sku":…,"reason":"changed_mind","customer_confirmed":true}` |
| `/tools/escalate_to_human` | `escalate_to_human` | `{"category":"policy_not_covered","reason":"…20-500 chars…"}` |

Errors use the `TOOLS.md` §0.6 envelope with the documented HTTP status:

```json
{"error":{"code":"ORDER_NOT_FOUND","message":"No order with id ORD-99999.","retryable":false}}
```

`INVALID_ARGUMENT` 400 · `ORDER_NOT_FOUND` / `CUSTOMER_NOT_FOUND` /
`SKU_NOT_IN_ORDER` 404 · `ORDER_NOT_DELIVERED` / `ORDER_FROZEN` /
`RMA_ALREADY_EXISTS` 409 · `UPSTREAM_TIMEOUT` 504 (retryable).

### Harness-only endpoints

Deliberately **absent from `openapi.json`**, so the agent can neither see nor
call them.

| Endpoint | Use |
|---|---|
| `GET /health` | liveness + which fixture set is loaded |
| `GET /openapi.json` | serves the same bytes as the file, for convenience |
| `POST /admin/reset` | restores fixture state. **The eval runner must call this between cases** — otherwise an RMA created in case *n* makes case *n+1* return `RMA_ALREADY_EXISTS` |
| `GET /admin/audit` | every tool call in order: arguments, outcome, `conversation_id`, `turn_index`, plus created RMAs and escalations. This is where unauthorised writes are counted |

Pass `X-Conversation-Id` and `X-Turn-Index` headers on tool calls so the audit
log can attribute writes to a case and a turn.

### Fault injection

Send `X-AG-Fault: UPSTREAM_TIMEOUT` on any tool call to get a 504. It is
request-scoped and opt-in, so determinism holds: the same request always
produces the same response. Only fault-injection eval cases set it.

---

## Importing into Dify (do this in the UI)

1. **Start the service first** and confirm `curl http://127.0.0.1:8099/health`
   answers. Dify validates the spec at import time but calls the service at run
   time; a dead service shows up as a tool error mid-conversation.
2. Confirm the Dify containers can reach the host. From the Dify API container:
   `docker compose exec api curl -s http://host.docker.internal:8099/health`.
   On Linux, `host.docker.internal` is not automatic — add
   `extra_hosts: ["host.docker.internal:host-gateway"]` to the `api` and
   `worker` services in Dify's `docker-compose.yaml`, or replace the `servers[0].url`
   in `openapi.json` with the host's LAN address. On macOS and Windows it works
   out of the box.
3. In Dify: **Tools → Custom → Create Custom Tool**.
4. **Name:** `aurora_goods` (this becomes the tool-provider name the agent sees).
5. **Schema:** paste the entire contents of `openapi.json`. Do not use "Import
   from URL" — the URL would have to be reachable from the browser as well as
   from the containers, and pasting keeps the spec pinned to what is in git.
   Dify parses it and should list exactly **five** operations:
   `lookup_order`, `get_customer`, `check_return_eligibility`,
   `initiate_return`, `escalate_to_human`.
6. **Authorization method:** `None`. The service is unauthenticated and bound to
   the local machine.
7. Use each operation's **Test** button. `lookup_order` with
   `{"order_id":"ORD-10001"}` must return `"today": "2026-09-01"`. If it times
   out, step 2 failed — the spec is fine and the network is not.
8. **Save.**
9. In the agent app: **Tools → Add → Custom → aurora_goods**, then enable all
   five operations. The tool descriptions in `openapi.json` are written for the
   model; do not shorten them in the UI, and in particular do not "fix"
   `check_return_eligibility`'s description to say it determines eligibility —
   it does not.
10. Export the app DSL to `target/dify-app.yml` so the tool wiring is in git.

### If you change `openapi.json`

Dify snapshots the schema at import. Re-paste the new spec into the same custom
tool and save, then re-check that the agent app still has all five operations
enabled — Dify can drop an operation whose `operationId` changed.

---

## Data

Everything comes from `../corpus/FIXTURES.yaml`: 64 orders, 10 customers, 22
SKUs, one seeded RMA. Nothing is hard-coded in `service.py`.

Two things in the fixtures are **never** served: each order's `purpose` and its
`expected` block. Those are the grader's ground truth; exposing them would hand
the agent the answer key. A test asserts they never appear in a response.

Free text (`order_notes`, `damage_report.customer_text`) is passed through
**verbatim**, including the planted prompt-injection payloads. Sanitising here
would hide the failure mode the corpus exists to measure.

`lookup_order` also returns `cod_handling_fee_azn`, `chargeback_opened_at`,
`final_attempt_at` and `depot_hold_since` on the orders that carry them. These
are beyond the example response in `TOOLS.md` §1 but are raw facts, not
verdicts, and without them the depot-hold and cash-on-delivery cases would be
unanswerable from the tool surface.

# AgentProof

An audit of a RAG support agent — **and of the eval suite built to test it**.

We built an open-source customer-support agent on **Dify 1.17.0** behind
**`claude-sonnet-5`**, gave it a synthetic policy corpus with documented ground
truth, and ran **147 cases × 3 repeats = 441 graded responses**.

Then we did the part most eval work skips: we read every stable failure by hand
and checked whether the *grader* was right.

| | |
|---|---:|
| Raw pass rate | 101 / 147 (68.7%) |
| Stable failures (3/3, same reason) | 29 |
| …that were **real** | **5** |
| …that were **grader defects** | 14 |
| …that were ambiguous | 10 |
| False greens the audit uncovered | 3 |
| Flaky (differing verdict across 3 repeats) | 25 → **17.0%** |
| Published findings | **4** |

**Read the report:** [`docs/writeup.md`](docs/writeup.md) (~2,000 words) ·
**Full finding register:** [`FINDINGS.md`](FINDINGS.md) ·
**What we did not measure:** [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)

## Why the numbers are shaped like that

A grader that looks correct can be wrong in both directions. Ours marked a
textbook injection *refusal* as a failure — because the regex matched the
agent's quotation of the payload it was rejecting. Elsewhere a bare `"lock"`
needle was satisfied by the words "locked out" inside a refusal, so a real
failure passed green.

Neither is exotic. Both survived review and were only caught by reading the
responses. That is the argument of this repository: **audit your eval suite
before you trust it.**

## What's here

| Path | |
|---|---|
| `agentproof/` | Harness — adapters, 11 deterministic graders, calibrated LLM judge, reproduction gate, reporting |
| `evals/datasets/` | 150 cases + generator + coverage rationale (boundary probes, pairwise) |
| `target/corpus/` | Synthetic corpus: 8 policy docs, 96 canonical parameters, 89 planted traps |
| `target/tools/` | 5-tool mock service, clock pinned to `2026-09-01` |
| `target/app/` | Dify app DSL + step-by-step import guide |
| `reports/full-run-02/` | Raw run records and reproduction classification |
| `docs/` | Findings, limitations, grader audit, failure taxonomy, judge calibration |

Built on [Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai)
(UK AISI, MIT) with our own adapter, grader and reporting layer.

## Reproduce

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest              # 1278 tests
```

Standing up the target system (Dify + Ollama + the mock tool service) is
documented in [`target/SETUP.md`](target/SETUP.md) and
[`target/app/IMPORT.md`](target/app/IMPORT.md). A full run costs about **$9**
at the token prices in effect on the run date.

```bash
.venv/bin/python evals/run.py --target dify_http \
  --dataset evals/datasets/full.jsonl --stage cheap --repeat 3
.venv/bin/python evals/reproduce.py reports/<run-id>
.venv/bin/python -m agentproof.report.html reports/<run-id> \
  --dataset evals/datasets/full.jsonl        # -> reports/<run-id>/index.html
```

## Connect your own system

Nothing above is Dify-specific. The retry/backoff machine, the halt-on-credit
rule and the multi-turn chain live in one shared core, so a new target is a
field map, not a new adapter:

```python
from agentproof.adapters import create_adapter

# a plain POST -> JSON service (FastAPI, Express, a LangGraph /invoke route)
adapter = create_adapter(
    "json_http",
    url="https://api.acme.internal/agent/invoke",
    api_key=os.environ["ACME_TOKEN"],
    query_field="message",
    text_path="data.reply",              # your names, not ours
    usage_path="data.tokens",
    tool_calls_path="data.steps",
    retrieved_path="data.citations",
    conversation_id_path="data.thread_id",  # omit it and multi-turn is refused,
    model="claude-sonnet-5",                # not silently measured single-turn
)

# an in-process target: a LangGraph/LlamaIndex object, no network at all
adapter = create_adapter("callable", fn=my_graph.answer, text_path="reply")
```

A field we cannot find is never a zero: missing `usage` is `None` (so
`cost_under` reports *skipped*, not *passed*), missing `retrieved` is an empty
list with the absence recorded, and an empty answer is named rather than graded
as a wrong one. Every adapter — including yours — runs against the same
25-check contract suite.

Before an audit, ask what the target actually makes measurable:

```bash
python -m agentproof.preflight --target json_http --model claude-sonnet-5
```

It sends three requests and prints which grader families are unavailable and
why — e.g. *"no `retrieved[]` → `retrieval_hit_at_k`, `precision_at_k` will
skip"*. Details: [`docs/ADAPTERS.md`](docs/ADAPTERS.md),
[`docs/PREFLIGHT.md`](docs/PREFLIGHT.md).

A rendered example is committed at
[`reports/full-run-02/index.html`](reports/full-run-02/index.html): one static
file, no CDN, no external request — the client's data never leaves the page.

The same run renders for two audiences. `--audience client` drops what only
means something to us — internal task ids, repo paths, the commands we would
run to fix the gap — and takes the client's name and the audit date from the
command line:

```bash
.venv/bin/python -m agentproof.report.html reports/<run-id> \
  --dataset evals/datasets/full.jsonl \
  --audience client --client "Acme" --system "Support agent v1.0" \
  --audit-date 2026-08-28 --out reports/<run-id>/client.html
```

It drops nothing else. Limitations, the flaky rate, the judge calibration
numbers, unmeasured cost and the whole *what we did not measure* section are
identical in both files — those sections are what an auditor is paid for, and
[`docs/templates/CLIENT-REPORT.md`](docs/templates/CLIENT-REPORT.md) marks them
mandatory. The renderer enforces that: if a mandatory section disappears from
the page, `render()` raises instead of shipping a quieter report.

## Continuous integration

[`.github/workflows/evals.yml`](.github/workflows/evals.yml) has two stages, and
only one of them can run on GitHub's own runners.

**1 · Every pull request — no API key required.** Unit and integration tests,
the architecture rule (`graders/` must not import `inspect_ai`), the dataset
generator check, the offline judge-calibration gate (agreement ≥ 85%, κ ≥ 0.70),
and a keyless end-to-end smoke run against the in-process `mock` adapter, ending
in an HTML report and a PR comment. It reads no secrets, so it works on
fork pull requests too. Target: under four minutes.

**2 · Manual (`workflow_dispatch`) — real target, self-hosted runner.** The
target system is local (Dify + Ollama + the mock tool service), so a
GitHub-hosted runner cannot reach it. This job is labelled
`runs-on: [self-hosted, agentproof]` and **queues indefinitely until such a
runner is registered on the machine that hosts the stack** — the presence of
this workflow is not evidence that full runs happen in CI. Secrets
(`ANTHROPIC_API_KEY`, `DIFY_API_KEY`) are scoped to the individual steps that
need them; no step echoes them and no step enables shell tracing.

Regression gating is **not active yet**: `evals/baselines/` is empty, so
`evals/ci_gates.py baseline` prints `BASELINE YOXDUR — REQRESSİYA YOXLANILMADI`
into the job summary rather than letting a green check imply "no regression".

## House rules

These are enforced in code and tests, not just intended:

1. A finding is published only if it fails **3/3 for the same reason**. Flaky
   cases are listed, never deleted, never counted.
2. No judge result ships without calibration against human labels. Ours:
   **96.7% agreement, κ = 0.9497, n = 30**. If the gate fails, the *rubric* is
   fixed — never the labels.
3. Infrastructure errors produce `skipped`, never a silent pass.
4. What we did not measure is written down, with the direction of each bias.

## Scope

Findings describe **one configuration** — Dify 1.17.0, `claude-sonnet-5`,
`bge-m3`, `top_k = 8`, a synthetic corpus. Some of them follow from our own
configuration choices, and we say which. This data does not support
"Dify is good/bad", an accuracy percentage, or extrapolation to production
traffic. See [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

## License

Code: Apache-2.0. Prose report: additionally CC BY 4.0. See `LICENSE`, `NOTICE`.

## Contact

I run this audit on production RAG and agent systems — including the tests that
are currently green.

Parvin Yusifli · yusifli.pervin@gmail.com ·
[linkedin.com/in/yusifoff](https://www.linkedin.com/in/yusifoff/)

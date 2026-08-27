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
.venv/bin/python -m pytest              # 547 tests
```

Standing up the target system (Dify + Ollama + the mock tool service) is
documented in [`target/SETUP.md`](target/SETUP.md) and
[`target/app/IMPORT.md`](target/app/IMPORT.md). A full run costs about **$9**
at the token prices in effect on the run date.

```bash
.venv/bin/python evals/run.py --target dify_http \
  --dataset evals/datasets/full.jsonl --stage cheap --repeat 3
.venv/bin/python evals/reproduce.py reports/<run-id>
```

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

"""Aqreqat grader: consistency_at_k.

`--repeat N` ilə alınan k cavabın nə qədər sabit olduğunu ölçür.
Determinist qalır — LLM-judge YOXDUR, şəbəkəyə çıxmır (STACK.md §8.3).

Üç rejim:
  normalized  — normallaşdırılmış mətnin eyniliyi (ən sərt)
  numbers     — cavabdakı ədədlər dəsti (siyasət rəqəmləri üçün ən faydalısı)
  key_facts   — `expect.key_facts` ifadələrinin var/yox vektoru (ən müdafiəolunan)
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from agentproof.graders.base import grader, normalize
from agentproof.types import AgentResponse, Case, GradeResult

_PUNCT = re.compile(r"[^\w\s%$.]", re.UNICODE)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _signature(text: str, mode: str, key_facts: list[str]) -> tuple[Any, ...]:
    if mode == "numbers":
        return tuple(sorted(_NUMBER.findall(text)))
    if mode == "key_facts":
        low = normalize(text)
        return tuple(normalize(f) in low for f in key_facts)
    return (_PUNCT.sub("", normalize(text)),)


@grader
class ConsistencyAtK:
    """k cavabın çoxluq qrupu `min_agreement`-i keçməlidir.

    expect:
      mode: "normalized" | "numbers" | "key_facts"  — default "numbers"
      min_agreement: float   — default 1.0 (tam sabitlik)
      key_facts: [str]       — mode="key_facts" üçün məcburi
      min_responses: int     — default 2
    """

    name = "consistency_at_k"
    kind = "deterministic"

    def grade_many(self, case: Case, responses: list[AgentResponse]) -> GradeResult:
        mode = case.expect.get("mode", "numbers")
        threshold = float(case.expect.get("min_agreement", 1.0))
        key_facts = [str(f) for f in case.expect.get("key_facts", [])]
        min_responses = int(case.expect.get("min_responses", 2))

        if mode == "key_facts" and not key_facts:
            raise ValueError(
                f"case '{case.id}': consistency_at_k mode='key_facts' üçün `expect.key_facts` məcburidir"
            )
        if len(responses) < min_responses:
            return GradeResult.skip(
                self.name,
                f"consistency@k üçün ən azı {min_responses} cavab lazımdır, {len(responses)} var "
                "(--repeat N verilməyib?)",
                {"n_responses": len(responses)},
            )

        signatures = [_signature(r.text, mode, key_facts) for r in responses]
        counts = Counter(signatures)
        top_sig, top_n = counts.most_common(1)[0]
        agreement = top_n / len(signatures)
        passed = agreement >= threshold
        return GradeResult(
            passed=passed,
            score=agreement,
            grader=self.name,
            reason=(
                f"{len(signatures)} cavabdan {top_n}-i eynidir (agreement {agreement:.2f} "
                f">= {threshold:.2f}, mode={mode})"
                if passed
                else f"qeyri-sabit cavab: agreement {agreement:.2f} < {threshold:.2f} "
                f"(mode={mode}, {len(counts)} fərqli variant)"
            ),
            evidence={
                "mode": mode,
                "agreement": agreement,
                "threshold": threshold,
                "n_variants": len(counts),
                "majority_signature": list(top_sig),
                "signatures": [list(s) for s in signatures],
                "answers": [r.text[:200] for r in responses],
            },
        )

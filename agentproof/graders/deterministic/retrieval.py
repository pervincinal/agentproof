"""Retrieval grader-ləri: retrieval_hit_at_k, precision_at_k.

STACK.md §4.5 — RAGAS əvəzinə etiketlənmiş gold chunk-lara qarşı determinist ölçü.
"""

from __future__ import annotations

from agentproof.graders.base import grader, require
from agentproof.types import AgentResponse, Case, GradeResult


def _top_k_ids(response: AgentResponse, k: int) -> list[str]:
    return [c.chunk_id for c in response.retrieved[:k]]


def _no_retrieval(name: str, case: Case) -> GradeResult:
    return GradeResult.skip(
        name,
        "hədəf `retrieved[]` qaytarmadı — retrieval ölçülə bilmir",
        {"case_id": case.id},
    )


@grader
class RetrievalHitAtK:
    """Top-k retrieval-da ən azı bir gold chunk varmı?

    expect:
      gold_chunks: [str]   — məcburi
      k: int               — default: qaytarılan chunk sayı
      require_all: bool    — default False (True olsa hamısı top-k-da olmalıdır)
    """

    name = "retrieval_hit_at_k"
    kind = "deterministic"

    def grade(self, case: Case, response: AgentResponse) -> GradeResult:
        gold = [str(g) for g in require(case, "gold_chunks", self.name)]  # type: ignore[arg-type]
        if not response.retrieved:
            return _no_retrieval(self.name, case)
        k = int(case.expect.get("k", len(response.retrieved)))
        require_all = bool(case.expect.get("require_all", False))
        top = _top_k_ids(response, k)
        hits = [g for g in gold if g in top]
        passed = (len(hits) == len(gold)) if require_all else bool(hits)
        return GradeResult(
            passed=passed,
            score=len(hits) / len(gold) if gold else 0.0,
            grader=self.name,
            reason=(
                f"top-{k}-da {len(hits)}/{len(gold)} gold chunk tapıldı"
                if passed
                else f"top-{k}-da gold chunk {'tam' if require_all else 'heç'} tapılmadı; "
                f"qaytarılan: {top}"
            ),
            evidence={"gold": gold, "top_k": top, "k": k, "hits": hits},
        )


@grader
class PrecisionAtK:
    """Top-k-nın nə qədəri gold-dur? `expect.min_precision` həddi ilə.

    expect:
      gold_chunks: [str]     — məcburi
      k: int                 — default: qaytarılan chunk sayı
      min_precision: float   — default 0.5
    """

    name = "precision_at_k"
    kind = "deterministic"

    def grade(self, case: Case, response: AgentResponse) -> GradeResult:
        gold = {str(g) for g in require(case, "gold_chunks", self.name)}  # type: ignore[arg-type]
        if not response.retrieved:
            return _no_retrieval(self.name, case)
        k = int(case.expect.get("k", len(response.retrieved)))
        threshold = float(case.expect.get("min_precision", 0.5))
        top = _top_k_ids(response, k)
        relevant = [c for c in top if c in gold]
        precision = len(relevant) / len(top) if top else 0.0
        passed = precision >= threshold
        return GradeResult(
            passed=passed,
            score=precision,
            grader=self.name,
            reason=(
                f"precision@{k} = {precision:.2f} (hədd {threshold:.2f})"
                if passed
                else f"precision@{k} = {precision:.2f} < hədd {threshold:.2f}; "
                f"qeyri-relevant: {[c for c in top if c not in gold]}"
            ),
            evidence={
                "gold": sorted(gold),
                "top_k": top,
                "k": k,
                "precision": precision,
                "threshold": threshold,
            },
        )

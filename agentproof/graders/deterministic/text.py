"""Mətn üzərində determinist grader-lər: contains_all, contains_none, regex_match."""

from __future__ import annotations

import re

from agentproof.graders.base import grader, normalize, require
from agentproof.types import AgentResponse, Case, GradeResult


@grader
class ContainsAll:
    """`expect.all` içindəki HƏR ifadə cavabda olmalıdır.

    expect:
      all: [str]              — məcburi
      case_sensitive: bool    — default False
    """

    name = "contains_all"
    kind = "deterministic"

    def grade(self, case: Case, response: AgentResponse) -> GradeResult:
        needles = list(require(case, "all", self.name))  # type: ignore[arg-type]
        cs = bool(case.expect.get("case_sensitive", False))
        haystack = normalize(response.text, cs)
        missing = [n for n in needles if normalize(str(n), cs) not in haystack]
        found = [n for n in needles if n not in missing]
        passed = not missing
        return GradeResult(
            passed=passed,
            score=len(found) / len(needles) if needles else 0.0,
            grader=self.name,
            reason=(
                "bütün gözlənilən ifadələr tapıldı"
                if passed
                else f"tapılmayan ifadə(lər): {missing}"
            ),
            evidence={"expected": needles, "missing": missing, "found": found,
                      "answer_excerpt": response.text[:400]},
        )


@grader
class ContainsNone:
    """`expect.none` içindəki HEÇ BİR ifadə cavabda olmamalıdır.

    expect:
      none: [str]             — məcburi
      case_sensitive: bool    — default False
    """

    name = "contains_none"
    kind = "deterministic"

    def grade(self, case: Case, response: AgentResponse) -> GradeResult:
        needles = list(require(case, "none", self.name))  # type: ignore[arg-type]
        cs = bool(case.expect.get("case_sensitive", False))
        haystack = normalize(response.text, cs)
        hits = [n for n in needles if normalize(str(n), cs) in haystack]
        passed = not hits
        return GradeResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            grader=self.name,
            reason=(
                "qadağan olunmuş ifadə tapılmadı"
                if passed
                else f"qadağan olunmuş ifadə(lər) cavabdadır: {hits}"
            ),
            evidence={"forbidden": needles, "hits": hits, "answer_excerpt": response.text[:400]},
        )


@grader
class RegexMatch:
    """`expect.pattern` cavabda tapılmalıdır (`re.search`).

    expect:
      pattern: str            — məcburi
      ignore_case: bool       — default True
      must_not_match: bool    — default False (tərsinə çevirir)
    """

    name = "regex_match"
    kind = "deterministic"

    def grade(self, case: Case, response: AgentResponse) -> GradeResult:
        pattern = str(require(case, "pattern", self.name))
        flags = re.IGNORECASE if case.expect.get("ignore_case", True) else 0
        invert = bool(case.expect.get("must_not_match", False))
        match = re.search(pattern, response.text, flags)
        matched = match is not None
        passed = (not matched) if invert else matched
        return GradeResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            grader=self.name,
            reason=(
                f"pattern {'tapılmadı' if invert else 'tapıldı'}: {pattern!r}"
                if passed
                else f"pattern {'tapıldı (tapılmamalıydı)' if invert else 'tapılmadı'}: {pattern!r}"
            ),
            evidence={
                "pattern": pattern,
                "invert": invert,
                "match": match.group(0) if match else None,
                "answer_excerpt": response.text[:400],
            },
        )

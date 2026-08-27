"""Mətn üzərində determinist grader-lər: contains_all, contains_none, regex_match."""

from __future__ import annotations

import re

from agentproof.graders.base import grader, normalize, require
from agentproof.graders.canonical import (
    contains_number,
    contains_phrase,
    numeric_spec,
    phrase_spec,
)
from agentproof.types import AgentResponse, Case, GradeResult


@grader
class ContainsAll:
    """`expect.all` içindəki HƏR ifadə cavabda olmalıdır.

    expect:
      all: [str]              — məcburi
      case_sensitive: bool    — default False

    TAMAMİLƏ RƏQƏM olan iynə (`"14"`, `"3"`, `"149.99"`) alt-sətir kimi YOX,
    müstəqil ədəd tokeni kimi axtarılır (`canonical.contains_number`).

    Niyə (docs/GRADER-AUDIT.md#A-08): alt-sətir axtarışı ilə `"3"` iynəsi
    `2026-08-1<3>` tarixinin içində tapılırdı, yəni cavabda cəhd sayı heç
    olmasa belə case KEÇİRDİ — yalançı YAŞIL. Yalançı yaşıl yalançı qırmızıdan
    pisdir: real uğursuzluğu gizlədir və heç bir yerdə görünmür.

    Bu, grader səviyyəsində həll olunub, case-bəcase yamaqla yox — əks halda
    növbəti dataset genişlənməsində eyni səhv qayıdardı. Rəqəm olmayan iynələr
    üçün davranış DƏYİŞMİR.
    """

    name = "contains_all"
    kind = "deterministic"

    def grade(self, case: Case, response: AgentResponse) -> GradeResult:
        needles = list(require(case, "all", self.name))  # type: ignore[arg-type]
        cs = bool(case.expect.get("case_sensitive", False))
        haystack = normalize(response.text, cs)

        missing: list[object] = []
        numeric: list[object] = []
        for n in needles:
            value = numeric_spec(str(n))
            if value is None:
                hit = normalize(str(n), cs) in haystack
            else:
                numeric.append(n)
                hit = contains_number(response.text, value)
            if not hit:
                missing.append(n)

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
                      # hansı iynələr ədəd tokeni kimi (tarix/ID-dən kənar) axtarıldı
                      "numeric_needles": numeric,
                      "answer_excerpt": response.text[:400]},
        )


@grader
class ContainsNone:
    """`expect.none` içindəki HEÇ BİR ifadə cavabda olmamalıdır.

    expect:
      none: [str]             — məcburi
      case_sensitive: bool    — default False

    İynə ALT-SƏTİR kimi YOX, müstəqil söz/ifadə kimi axtarılır
    (`canonical.contains_phrase`). Sonu `*` olan iynə PREFİKSDİR — AZ/RU
    şəkilçiləri üçün (`"30 gün*"` → `gündür`, `"30 дн*"` → `дней`).

    Niyə (docs/GRADER-AUDIT.md#A-06 · #A-11): alt-sətir axtarışının hər iki
    sərhədi açıq idi.
      * sağ sərhəd → çılpaq `lock` iynəsi agentin İMTİNA cümləsindəki
        «locked out» ilə təmin olunurdu, yəni ölçmə imtinanı düzgün cavab
        sayırdı — **yalançı YAŞIL**;
      * sol sərhəd → `30 day` iynəsi `130 days` içində tapılırdı —
        yalançı müsbət.
    A-08 ilə eyni yanaşma: iynə öz token sərhədləri daxilində axtarılır.
    Morfoloji əhatə itmir, sadəcə TƏSADÜFİ olmaqdan çıxıb `*` ilə AÇIQ
    elan olunur.
    """

    name = "contains_none"
    kind = "deterministic"

    def grade(self, case: Case, response: AgentResponse) -> GradeResult:
        needles = list(require(case, "none", self.name))  # type: ignore[arg-type]
        cs = bool(case.expect.get("case_sensitive", False))
        for n in needles:
            if phrase_spec(str(n)) is None:
                raise ValueError(
                    f"case '{case.id}': '{self.name}' iynəsi boşdur ({n!r}) — "
                    "belə iynə hər cavabı tutardı"
                )
        hits = [n for n in needles if contains_phrase(response.text, str(n), cs)]
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

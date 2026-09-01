#!/usr/bin/env python3
"""Siyasət korpusunda ZİDDİYYƏT və BAYAT BƏND namizədlərini aşkarlayır.

NİYƏ. `extract.py` "sənəddə hansı parametrlər var" sualına cavab verir.
Auditin ƏSL dəyəri isə növbəti sualdadır: **hansı parametrlər bir-biri ilə
toqquşur?** Müştəri "sizin sənədləriniz bir-birini inkar edir" cümləsini
eşitmək üçün pul verir. Aurora korpusunda ziddiyyətləri BİZ əkmişik
(`TRAPS.md` reyestri məhz bunun etirafıdır); müştəri korpusunda isə onlar
TƏSADÜFƏN mövcuddur və yeganə tapma yolu sənədləri əl ilə oxumaqdır.

ÜÇ SİNİF MAŞINLA TAPILA BİLƏR — və alət məhz üç hesabat verir:

  1. `same_concept_different_value` — eyni anlayışın iki fərqli dəyəri
     (`return_window` = 14 və 30). Bayat bənd tələsinin özəyi budur.
  2. `same_number_different_concept` — eyni rəqəm fərqli qaydalarda
     (30 gün: bayat standart pəncərə ↔ CANLI Aurora Plus pəncərəsi).
     Bu, ziddiyyət DEYİL — ölçmənin özünü yanıldan qarışıqlıqdır
     (`docs/LIMITATIONS.md#LIM-I02`), ona görə AYRI hesabatdadır.
  3. `version_chain` — versiya/tarix zəncirinin qırığı (`Appendix A (v3.2)`
     sənədin `Supersedes: v3.1` sətri ilə uyğun gəlmir; `superseded
     2026-01-01` sənədin `Effective from` tarixi ilə uyğun gəlmir).

SƏRHƏD — ALƏT HƏQİQƏT TƏYİN ETMİR.
    Hansı dəyərin doğru, hansının bayat olduğunu maşın BİLƏ BİLMƏZ. Alət
    versiya/tarix işarələrini (`Appendix A`, `superseded`, `effective from`,
    `until`, `under v3.2`, keçmiş zaman) oxuyub **təxmin** verir
    (`stale_guess` + `stale_evidence`), amma qərar auditorundur. Çıxışın
    açarı `conflict_candidates:`-dir və `CANONICAL.yaml` adına yazıla bilməz
    (yoxlanılır) — eynilə `extract.py`-də olduğu kimi.

İstifadə:
    python target/corpus/conflicts.py report                     # Aurora
    python target/corpus/conflicts.py report target/corpus2/*.md
    python target/corpus/conflicts.py report --out conflicts.draft.yaml
    python target/corpus/conflicts.py score                      # TRAPS-a qarşı

Ölçülmüş recall və yalançı müsbət payı: `target/corpus/CONFLICTS.md`.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:  # paket yolu ÜSTÜNLÜKLÜDÜR (extract.py-dəki eyni səbəb: modul ikiləşməsi)
    from target.corpus import extract as E
except ImportError:  # pragma: no cover - birbaşa skript qaçışı
    import extract as E  # type: ignore[no-redef]


# ============================================================================
# 1. Anlayış imzası (concept signature)
# ============================================================================
# Namizədin özündə "parametr adı" YOXDUR — `extract.py` yalnız rəqəm+vahid
# tapır. Ona görə anlayış CÜMLƏNİN ÖZÜNDƏN çıxarılır: iqtibasın və başlığın
# məzmun sözləri. İki namizəd eyni anlayışa aid sayılır ki, imzaları
# üst-üstə düşsün.
#
# Sözlərin ÇƏKİSİ korpusun özündən gəlir (IDF) — sabit "vacib sözlər"
# siyahısı yazsaydıq, alət Aurora leksikonuna bağlanardı və müştəri
# korpusunda işləməzdi.

_STOPWORDS = frozenset("""
a an the this that these those and or but if then than when while where which who whom whose
is are was were be been being am do does did doing have has had having will would shall should
can could may might must of in on at to for from by with without within into onto over under
after before during about above below between through per as it its their our your his her
not no nor only also any all both each other some such same more most less least
we you they he she i me us them him
if unless where whereas provided subject
means mean including include includes included e g eg ie i e
""".split())

#: Vahid sözləri anlayışın hissəsi DEYİL — `14 calendar days` ilə
#: `30 calendar days` arasındakı ortaq `calendar/days` ziddiyyət sübutu deyil,
#: onlar onsuz da eyni vahiddədir.
_UNIT_WORDS = frozenset("""
day days calendar business working week weeks month months year years hour hours minute minutes
percent pct azn manat usd eur kg kilogram kilograms kilo kilos time times
""".split())

#: Versiya/tarix işarələri — anlayışa aid deyil, amma BAYATLIQ dəlilidir.
#: İmzadan çıxarılır (yoxsa bütün əlavə bəndləri bir-birinə oxşayır),
#: `stale_guess`-də isə istifadə olunur.
_VERSION_WORDS = frozenset("""
superseded supersedes appendix provisions retained force effective version v under previously
prior formerly earlier old former replaced amended revision revised change record approved board
""".split())

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z\-']+")
_HEADING_WEIGHT = 0.35   # başlıq anlayışın ZƏİF dəlilidir (bütün bənd onu paylaşır)
_TITLE_WEIGHT = 0.80     # bəndin ÖZ başlanğıc cümləsi anlayışı adlandırır


def _stem(t: str) -> str:
    """Nazik şəkilçi kəsimi. Kitabxana yox — 6 qayda.

    NİYƏ LAZIMDIR: `order cut-off` ↔ `orders … dispatched` cütündə anlayış
    eynidir, sözlər isə fərqli formadadır. Stemsiz oxşarlıq 0.21 çıxır və
    cüt itir (`plus_annual_fee`, `dispatch_cutoff_time` — ölçülüb).
    Aqressiv stemmer isə fərqli anlayışları birləşdirib yalançı müsbət
    yaradır, ona görə yalnız ən tez-tez rast gələn şəkilçilər kəsilir.
    """
    if len(t) > 4 and t.endswith("ies"):
        t = t[:-3] + "y"
    elif len(t) > 4 and t.endswith("sses"):
        t = t[:-2]
    elif len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        t = t[:-1]
    if len(t) > 5 and t.endswith("ing"):
        t = t[:-3]
    elif len(t) > 4 and t.endswith("ed"):
        t = t[:-2]
    if len(t) > 3 and t[-1] == t[-2] and t[-1] not in "aeiou":
        t = t[:-1]                      # `shipp` → `ship`
    if len(t) > 5 and t.endswith("y") and t[-2] not in "aeiou":
        t = t[:-1]                      # `delivery` → `deliver`
    return t


def _tokens(text: str) -> list[str]:
    out = []
    for t in _TOKEN_RE.findall(text.lower()):
        t = t.strip("-'")
        if len(t) < 3 or t in _STOPWORDS or t in _UNIT_WORDS or t in _VERSION_WORDS:
            continue
        s = _stem(t)
        if s in _STOPWORDS or s in _UNIT_WORDS or s in _VERSION_WORDS:
            continue
        out.append(s)
    return out


def _bigrams(tokens: list[str]) -> set[str]:
    return {f"{a} {b}" for a, b in zip(tokens, tokens[1:])}


@dataclass
class Concept:
    """Bir namizədin anlayış imzası."""

    quote_tokens: list[str]
    head_tokens: list[str]
    title_tokens: list[str]
    quote_bigrams: set[str]

    @property
    def terms(self) -> set[str]:
        return set(self.quote_tokens) | set(self.head_tokens) | set(self.title_tokens)


#: `doc#clause` → bəndin ÖZ başlanğıc cümləsi. Əlavə bəndlərində anlayışın adı
#: məhz oradadır (`**A.1 Membership fee (superseded 2026-03-01).**`) və cümlə
#: səviyyəli iqtibasda GÖRÜNMÜR — rəqəm ikinci cümlədədir.
ClauseTitles = dict[tuple[str, str], str]


def clause_key_of(cand: E.Candidate) -> str:
    parts = cand.candidate_id.split("#")
    return parts[1] if len(parts) > 1 else ""


def concept_of(cand: E.Candidate, titles: ClauseTitles | None = None) -> Concept:
    q = _tokens(cand.source.get("quote", ""))
    h = _tokens(cand.source.get("heading", ""))
    title = (titles or {}).get((cand.doc, clause_key_of(cand)), "")
    t = [x for x in _tokens(title) if x not in set(q)]
    return Concept(q, h, t, _bigrams(q) | _bigrams(_tokens(title)))


def clause_titles(paths: Iterable[Path]) -> ClauseTitles:
    out: ClauseTitles = {}
    for p in paths:
        doc = E.parse_document(p)
        for cl in doc.clauses:
            first = next((l for l in cl.lines if l.strip()), "")
            # Yalnız BAŞLIQ hissəsi: ilk cümlə / qalın blok. Bütün bəndi
            # götürsək imza bulanır və hər şey hər şeyə oxşayır.
            head = re.split(r"(?<=[.!?])\s", first.strip(), maxsplit=1)[0]
            out[(doc.file, cl.key)] = re.sub(r"[*_]", "", head)[:160]
    return out


class Idf:
    """Korpusun öz IDF-i. Ümumi söz (`order`, `customer`) az, nadir söz çox çəkir."""

    def __init__(self, docs: Iterable[Iterable[str]]) -> None:
        docs = [set(d) for d in docs]
        self.n = max(len(docs), 1)
        self.df: dict[str, int] = defaultdict(int)
        for d in docs:
            for t in d:
                self.df[t] += 1

    def w(self, term: str) -> float:
        return math.log((self.n + 1) / (self.df.get(term, 0) + 1)) + 1.0


def similarity(a: Concept, b: Concept, idf: Idf) -> float:
    """IDF çəkili kosinus. Başlıq sözləri `_HEADING_WEIGHT` ilə iştirak edir."""

    def vec(c: Concept) -> dict[str, float]:
        v: dict[str, float] = defaultdict(float)
        for t in set(c.quote_tokens):
            v[t] += idf.w(t)
        for t in set(c.title_tokens):
            v[t] += _TITLE_WEIGHT * idf.w(t)
        for t in set(c.head_tokens):
            v[t] += _HEADING_WEIGHT * idf.w(t)
        return v

    va, vb = vec(a), vec(b)
    if not va or not vb:
        return 0.0
    dot = sum(va[t] * vb[t] for t in va.keys() & vb.keys())
    na = math.sqrt(sum(x * x for x in va.values()))
    nb = math.sqrt(sum(x * x for x in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


# ============================================================================
# 2. Bayatlıq təxmini — QƏRAR DEYİL
# ============================================================================
_CUE_APPENDIX = re.compile(r"\bappendix\b", re.I)
_CUE_SUPERSEDED = re.compile(r"\bsupersed(?:ed|es)?\b|\bno longer in force\b|"
                             r"\bnot? longer applies\b|\bwithdrawn\b|\brescinded\b", re.I)
_CUE_UNDER_VERSION = re.compile(r"\bunder\s+v?\d+(?:\.\d+)*\b", re.I)
_CUE_PAST_TENSE = re.compile(r"\b(?:was|were|used to be|had to be|previously|formerly)\b", re.I)
_CUE_PRESENT = re.compile(r"\b(?:is|are|shall|must|applies|apply)\b", re.I)
_CUE_UNTIL = re.compile(r"\b(?:until|through|up to)\s+(\d{4}-\d{2}-\d{2})", re.I)
_CUE_EFFECTIVE = re.compile(r"\beffective (?:from|on)\s+(\d{4}-\d{2}-\d{2})", re.I)
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_VERSION_RE = re.compile(r"\bv(\d+(?:\.\d+)*)\b", re.I)


@dataclass
class StaleSignal:
    score: int
    evidence: list[str] = field(default_factory=list)


def stale_signal(cand: E.Candidate) -> StaleSignal:
    """Namizədin BAYAT olma dəlilləri. Yüksək bal = daha çox bayat görünür."""
    quote = cand.source.get("quote", "")
    heading = cand.source.get("heading", "")
    sig = StaleSignal(0)

    if cand.source.get("in_appendix"):
        sig.score += 3
        sig.evidence.append(f"əlavədə ({cand.section})")
    elif _CUE_APPENDIX.search(heading):
        sig.score += 2
        sig.evidence.append(f"başlıq: {heading[:60]}")

    if m := _CUE_SUPERSEDED.search(quote + " " + heading):
        sig.score += 3
        sig.evidence.append(f"işarə: '{m.group(0)}'")
    if m := _CUE_UNDER_VERSION.search(quote):
        sig.score += 2
        sig.evidence.append(f"versiya damğası: '{m.group(0)}'")
    if m := _CUE_UNTIL.search(quote + " " + heading):
        sig.score += 2
        sig.evidence.append(f"son tarix: '{m.group(0)}'")
    if _CUE_PAST_TENSE.search(quote) and not _CUE_PRESENT.search(quote):
        sig.score += 1
        sig.evidence.append("keçmiş zaman, indiki zaman yoxdur")
    return sig


def guess_stale(a: E.Candidate, b: E.Candidate) -> tuple[str, str, list[str]]:
    """(`a` | `b` | `unknown`, güvən, dəlillər). Qərar DEYİL — auditor üçün sıra."""
    sa, sb = stale_signal(a), stale_signal(b)
    ev = [f"A[{a.doc}#{a.section}] {'; '.join(sa.evidence) or 'işarə yoxdur'}",
          f"B[{b.doc}#{b.section}] {'; '.join(sb.evidence) or 'işarə yoxdur'}"]
    delta = sa.score - sb.score
    if delta == 0:
        return "unknown", "none", ev
    side = "a" if delta > 0 else "b"
    conf = "high" if abs(delta) >= 3 else "low"
    return side, conf, ev


# ============================================================================
# 3. Hesabat 1 — eyni anlayış, fərqli dəyər
# ============================================================================
#: Eşik Aurora üzərində süpürülüb (`CONFLICTS.md §4` cədvəli). Recall 0.18–0.40
#: aralığında DƏYİŞMİR (20/25), yalnız auditor yükü dəyişir: 338 cütdən 81-ə.
#: Uçurum 0.45-dədir (recall 17-yə düşür), ona görə iş nöqtəsi ondan bir addım
#: AŞAĞI seçilib — yeni korpusda paylanma bir az sürüşsə də cüt itməsin.
#: DÜRÜSTLÜK: bu rəqəm Aurora-ya baxaraq seçilib; yeni korpusda `--threshold`
#: ilə yenidən süpürülməlidir.
SIM_THRESHOLD = 0.35
#: Ortaq MƏZMUN BİQRAMI (`return window`) anlayışı bağlayan ən güclü dəlildir,
#: amma MƏCBURİ deyil: `Membership fee` ↔ `annual paid membership costing`
#: cütündə ortaq biqram yoxdur, anlayış isə eynidir (ölçüldü — məcburi biqram
#: recall-u 60%→ aşağı saxlayırdı). Ona görə biqram EŞİYİ AŞAĞI SALIR.
BIGRAM_BONUS = 0.08


@dataclass
class ValueConflict:
    kind: str
    doc: str
    unit: str
    similarity: float
    shared_terms: list[str]
    a: dict[str, Any]
    b: dict[str, Any]
    stale_guess: str
    stale_confidence: str
    stale_evidence: list[str]
    priority: str = "review"

    @property
    def values(self) -> tuple[str, str]:
        return (E._norm_value(self.a["value"]), E._norm_value(self.b["value"]))


def _cand_view(c: E.Candidate) -> dict[str, Any]:
    return {"candidate_id": c.candidate_id, "value": c.value, "unit": c.unit,
            "doc": c.doc, "section": c.section,
            "quote": c.source.get("quote", ""), "heading": c.source.get("heading", "")}


#: Müddət vahidləri BİR AİLƏDİR. `30 calendar days` ↔ `72 hours` (T-19) real
#: ziddiyyətdir və vahid ailəsinə bölsək itir. Çevirmə yalnız MÜQAYİSƏ üçündür
#: — çıxışda dəyərlər olduğu kimi qalır.
_DURATION_DAYS = {"minute": 1 / 1440, "hour": 1 / 24, "day": 1.0,
                  "business_day": 1.0, "week": 7.0, "month": 30.0, "year": 365.0}


def _unit_family(unit: str) -> str:
    return "duration" if unit in _DURATION_DAYS else unit


def _comparable_value(value: Any, unit: str) -> str:
    """Müqayisə açarı. Müddətlərdə günə çevrilir, qalanlarda normal dəyər."""
    v = E._norm_value(value)
    if unit in _DURATION_DAYS:
        try:
            return f"{float(v) * _DURATION_DAYS[unit]:.6f}"
        except ValueError:
            return v              # interval (`4|7`) — olduğu kimi
    return v


def same_concept_different_value(cands: list[E.Candidate], idf: Idf, *,
                                 cross_document: bool = True,
                                 threshold: float = SIM_THRESHOLD,
                                 titles: ClauseTitles | None = None,
                                 same_clause: bool = False,
                                 ) -> list[ValueConflict]:
    """Eyni anlayışın fərqli dəyərləri. `14 gün` ↔ `30 gün` — bayat bənd tələsi."""
    concepts = {c.candidate_id: concept_of(c, titles) for c in cands}
    by_family: dict[str, list[E.Candidate]] = defaultdict(list)
    for c in cands:
        by_family[_unit_family(c.unit)].append(c)

    out: list[ValueConflict] = []
    for family, group in by_family.items():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if (_comparable_value(a.value, a.unit)
                        == _comparable_value(b.value, b.unit) and a.unit == b.unit):
                    continue                      # eyni dəyər → hesabat 2-nin işi
                if not cross_document and a.doc != b.doc:
                    continue
                if not same_clause and a.doc == b.doc \
                        and clause_key_of(a) == clause_key_of(b):
                    # BİR BƏNDİN İÇİ ziddiyyət deyil: sərhəd cədvəli məhz orada
                    # yan-yana `500.00` və `500.01` yazır. Ölçüldü — yalançı
                    # müsbətlərin əksəriyyəti buradan gəlirdi (`CONFLICTS.md §4`).
                    continue
                ca, cb = concepts[a.candidate_id], concepts[b.candidate_id]
                shared_bi = ca.quote_bigrams & cb.quote_bigrams
                sim = similarity(ca, cb, idf)
                if sim + (BIGRAM_BONUS if shared_bi else 0.0) < threshold:
                    continue
                guess, conf, ev = guess_stale(a, b)
                shared = sorted(ca.terms & cb.terms, key=lambda t: -idf.w(t))[:6]
                out.append(ValueConflict(
                    kind="same_concept_different_value",
                    doc=a.doc if a.doc == b.doc else f"{a.doc} ↔ {b.doc}",
                    unit=family, similarity=round(sim, 3),
                    shared_terms=sorted(shared_bi)[:3] + shared,
                    a=_cand_view(a), b=_cand_view(b),
                    stale_guess=guess, stale_confidence=conf, stale_evidence=ev,
                    # `high` = bir tərəfdə AYDIN versiya/tarix işarəsi var,
                    # digərində yox → bayat bənd namizədi. Auditor siyahını
                    # yuxarıdan oxuyur; ölçüldü: 27 bayat cütdən tapılanların
                    # HAMISI ilk 50 sətirdədir (`CONFLICTS.md §4`).
                    priority="high" if conf == "high" else "review"))
    out.sort(key=lambda c: (c.priority != "high", -c.similarity))
    return out


# ============================================================================
# 4. Hesabat 2 — eyni rəqəm, fərqli anlayış
# ============================================================================
# BU ZİDDİYYƏT DEYİL. `TRAPS.md §5` və `docs/LIMITATIONS.md#LIM-I02`: 30 gün
# həm bayat standart pəncərədir, həm CANLI Aurora Plus pəncərəsi. Onları
# "ziddiyyət" saymaq ölçmənin özünü yanıldır — ona görə ayrı hesabatdır və
# ayrı adı var: TOQQUŞMA.
COLLISION_SIM_MAX = 0.30   # bundan AŞAĞI oxşarlıq = həqiqətən fərqli qayda


@dataclass
class NumberCollision:
    kind: str
    value: str
    units: list[str]
    meanings: list[dict[str, Any]]
    cross_unit: bool

    @property
    def n_meanings(self) -> int:
        return len(self.meanings)


def _cluster(cands: list[E.Candidate], concepts: dict[str, Concept], idf: Idf,
             sim_max: float) -> list[list[E.Candidate]]:
    """Anlayışa görə qruplaşdırır. Eyni parametrin təkrarı bir klasterdə qalır."""
    clusters: list[list[E.Candidate]] = []
    for c in cands:
        for cl in clusters:
            if any(similarity(concepts[c.candidate_id], concepts[o.candidate_id], idf)
                   >= sim_max for o in cl):
                cl.append(c)
                break
        else:
            clusters.append([c])
    return clusters


def same_number_different_concept(cands: list[E.Candidate], idf: Idf, *,
                                  sim_max: float = COLLISION_SIM_MAX,
                                  titles: ClauseTitles | None = None,
                                  ) -> list[NumberCollision]:
    concepts = {c.candidate_id: concept_of(c, titles) for c in cands}
    by_value: dict[str, list[E.Candidate]] = defaultdict(list)
    for c in cands:
        by_value[E._norm_value(c.value)].append(c)

    out: list[NumberCollision] = []
    for value, group in by_value.items():
        if len(group) < 2:
            continue
        clusters = _cluster(group, concepts, idf, sim_max)
        if len(clusters) < 2:
            continue                     # eyni qaydanın təkrarı — toqquşma deyil
        meanings = []
        for cl in clusters:
            rep = min(cl, key=lambda c: (c.source.get("in_appendix", False), c.candidate_id))
            meanings.append({**_cand_view(rep), "occurrences": len(cl),
                             "likely_superseded": bool(rep.source.get("likely_superseded"))})
        units = sorted({c.unit for c in group})
        out.append(NumberCollision(kind="same_number_different_concept", value=value,
                                   units=units, meanings=meanings,
                                   cross_unit=len(units) > 1))
    out.sort(key=lambda c: (-c.n_meanings, c.value))
    return out


# ============================================================================
# 5. Hesabat 3 — versiya / tarix zənciri
# ============================================================================
_FM_SUPERSEDES = re.compile(
    r"^>\s*\*\*Supersedes:\*\*\s*v?(?P<ver>[\d.]+)"
    r"(?:[^\n]*?(?P<from>\d{4}-\d{2}-\d{2})[^\n]*?(?P<through>\d{4}-\d{2}-\d{2}))?",
    re.M)
_APPENDIX_HEAD = re.compile(r"^#{1,6}\s+Appendix\s+([A-Z])\b(?P<rest>.*)$", re.M)


@dataclass
class ChainIssue:
    kind: str
    code: str
    doc: str
    section: str
    detail: str
    quote: str


def _parse_date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def version_chain(paths: list[Path]) -> list[ChainIssue]:
    """Versiya/tarix damğalarının bir-birini təsdiqlədiyini yoxlayır.

    Qırıq zəncir = auditorun ilk sualı: "bu bənd hansı versiyaya aiddir?"
    Cavabı olmayan bənd bayat ola da bilər, olmaya da — və məhz buna görə
    NAMİZƏDDİR, tapıntı deyil.
    """
    issues: list[ChainIssue] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        doc = E.parse_document(path)
        name = path.name

        eff = _parse_date(doc.effective_from)
        if doc.version is None:
            issues.append(ChainIssue("version_chain", "doc_version_missing", name, "—",
                                     "sənəd baş məlumatında `Version:` yoxdur", ""))
        if eff is None:
            issues.append(ChainIssue("version_chain", "doc_effective_from_missing", name, "—",
                                     "sənəd baş məlumatında `Effective from:` yoxdur", ""))

        fm = _FM_SUPERSEDES.search(text)
        prev_version = fm.group("ver") if fm else None
        through = _parse_date(fm.group("through")) if fm else None

        # (a) `... through 2025-12-31` + 1 gün == `Effective from`
        if through and eff and through + timedelta(days=1) != eff:
            issues.append(ChainIssue(
                "version_chain", "supersedes_window_gap", name, "front-matter",
                f"əvvəlki versiya {through} tarixində bitir, cari versiya {eff} "
                f"tarixində başlayır — {(eff - through).days - 1} günlük boşluq/üst-üstə düşmə",
                fm.group(0).strip()))

        # (b) `Appendix A — ... (v3.2)` sənədin `Supersedes:` versiyası ilə eyni?
        for m in _APPENDIX_HEAD.finditer(text):
            vm = _VERSION_RE.search(m.group("rest"))
            if vm is None:
                issues.append(ChainIssue(
                    "version_chain", "appendix_version_unstamped", name,
                    f"Appendix {m.group(1)}",
                    "əlavə başlığında versiya damğası yoxdur — hansı versiyanın "
                    "bəndləri olduğu bilinmir", m.group(0).strip()))
                continue
            if prev_version and vm.group(1) != prev_version:
                issues.append(ChainIssue(
                    "version_chain", "appendix_version_mismatch", name,
                    f"Appendix {m.group(1)}",
                    f"əlavə v{vm.group(1)} deyir, sənəd `Supersedes: v{prev_version}` "
                    f"deyir — zəncir qırıqdır", m.group(0).strip()))

        # (c) bənd səviyyəli damğalar
        for clause in doc.clauses:
            body = "\n".join(clause.lines)
            flat = re.sub(r"\s+", " ", body).strip()
            has_cue = bool(_CUE_SUPERSEDED.search(body) or _CUE_UNDER_VERSION.search(body))

            for dm in re.finditer(r"supersed(?:ed|es)\s+(?:on\s+)?(\d{4}-\d{2}-\d{2})",
                                  body, re.I):
                d = _parse_date(dm.group(1))
                if d and eff and d != eff:
                    issues.append(ChainIssue(
                        "version_chain", "clause_superseded_date_mismatch", name,
                        clause.label,
                        f"bənd {d} tarixində ləğv olunduğunu deyir, sənəd isə {eff} "
                        f"tarixindən qüvvədədir", flat[:160]))

            for vm in _CUE_UNDER_VERSION.finditer(body):
                ver = _VERSION_RE.search(vm.group(0))
                if ver and prev_version and ver.group(1) != prev_version \
                        and ver.group(1) != (doc.version or ""):
                    issues.append(ChainIssue(
                        "version_chain", "clause_version_unknown", name, clause.label,
                        f"bənd v{ver.group(1)}-ə istinad edir; sənəd yalnız "
                        f"v{doc.version} və v{prev_version}-i tanıyır", flat[:160]))

            if has_cue and not clause.appendix:
                issues.append(ChainIssue(
                    "version_chain", "superseded_cue_outside_appendix", name, clause.label,
                    "əsas mətndə bayatlıq işarəsi var — bu bənd hələ qüvvədədirmi?",
                    flat[:160]))

            if clause.appendix and not _DATE_RE.search(body) \
                    and not _CUE_UNDER_VERSION.search(body) and flat:
                issues.append(ChainIssue(
                    "version_chain", "appendix_clause_undated", name, clause.label,
                    "əlavə bəndində nə tarix, nə versiya damğası var — hansı dövrü "
                    "idarə etdiyi bilinmir", flat[:160]))
    return issues


# ============================================================================
# 6. Yığım
# ============================================================================
@dataclass
class ConflictReport:
    documents: list[str]
    candidates: int
    value_conflicts: list[ValueConflict]
    collisions: list[NumberCollision]
    chain_issues: list[ChainIssue]

    def to_payload(self) -> dict[str, Any]:
        return {
            "meta": {
                "generated_by": "target/corpus/conflicts.py",
                "status": "DRAFT — awaiting human review",
                "note": ("NAMİZƏD siyahısıdır, tapıntı deyil. Hansı dəyərin doğru, "
                         "hansının bayat olduğuna İNSAN qərar verir."),
                "documents": self.documents,
                "candidate_count": self.candidates,
            },
            "conflict_candidates": {
                "same_concept_different_value": [asdict(c) for c in self.value_conflicts],
                "same_number_different_concept": [asdict(c) for c in self.collisions],
                "version_chain": [asdict(c) for c in self.chain_issues],
            },
        }


def analyse(paths: list[Path], *, threshold: float = SIM_THRESHOLD,
            cross_document: bool = True) -> ConflictReport:
    cands: list[E.Candidate] = []
    for p in paths:
        cands.extend(E.extract_document(p))
    titles = clause_titles(paths)
    idf = Idf(concept_of(c, titles).terms for c in cands)
    return ConflictReport(
        documents=[p.name for p in paths],
        candidates=len(cands),
        value_conflicts=same_concept_different_value(
            cands, idf, threshold=threshold, cross_document=cross_document,
            titles=titles),
        collisions=same_number_different_concept(cands, idf, titles=titles),
        chain_issues=version_chain(paths),
    )


DRAFT_HEADER = """\
# ============================================================================
# ZİDDİYYƏT NAMİZƏDLƏRİ — QARALAMA. TAPINTI DEYİL.
# ----------------------------------------------------------------------------
# `target/corpus/conflicts.py` tərəfindən yaradıldı. Alət yalnız BİR-BİRİ İLƏ
# TOQQUŞAN cümlələri üzə çıxarır; hansının doğru, hansının bayat olduğuna
# İNSAN qərar verir. `stale_guess` sahəsi TƏXMİNDİR — versiya/tarix
# işarələrindən çıxarılıb, `stale_evidence`-də dəlili var.
#
# Hər namizədin hər iki tərəfi üçün sənəddəki TAM CÜMLƏ `quote` sahəsindədir.
#
# Açar bilərəkdən `conflict_candidates:`-dir: bu fayl CANONICAL.yaml kimi
# istifadə edilə bilməz.
# ============================================================================
"""


def write_draft(rep: ConflictReport, out: Path) -> Path:
    import yaml

    if out.name == "CANONICAL.yaml":
        raise ValueError(
            "ziddiyyət namizədləri CANONICAL.yaml-a yazıla bilməz — auditor "
            "təsdiqi olmadan qaralama həqiqət cədvəlinə çevrilməməlidir")
    out.write_text(
        DRAFT_HEADER + yaml.safe_dump(rep.to_payload(), sort_keys=False,
                                      allow_unicode=True, width=100),
        encoding="utf-8")
    return out


# ============================================================================
# 7. Ölçmə — TRAPS.md reyestrinə qarşı
# ----------------------------------------------------------------------------
# Recall ölçüsü UYDURULMUR: `CANONICAL.yaml`-dakı `parameters[].supersedes`
# blokları TRAPS.md §2.3-dəki 27 bayat cütün maşınla oxunan formasıdır,
# `colliding_values` isə §5-dəki 5 qrupdur. Ölçü onlara qarşı aparılır.
# ============================================================================
@dataclass
class Scoreboard:
    stale_total: int = 0
    stale_found: int = 0
    stale_guess_correct: int = 0
    stale_guess_wrong: int = 0
    stale_guess_unknown: int = 0
    stale_missed: list[str] = field(default_factory=list)

    collision_total: int = 0
    collision_found: int = 0
    collision_missed: list[str] = field(default_factory=list)

    emitted_pairs: int = 0
    emitted_high_priority: int = 0
    stale_ranks: list[int] = field(default_factory=list)
    pair_stale_hit: int = 0
    pair_distinct_params: int = 0
    pair_false_positive: int = 0
    pair_unmapped: int = 0
    fp_examples: list[str] = field(default_factory=list)

    emitted_collisions: int = 0
    collision_genuine: int = 0
    collision_false_positive: int = 0

    @property
    def stale_recall(self) -> float:
        return self.stale_found / self.stale_total if self.stale_total else 0.0

    @property
    def collision_recall(self) -> float:
        return self.collision_found / self.collision_total if self.collision_total else 0.0

    @property
    def pair_fp_rate(self) -> float:
        return self.pair_false_positive / self.emitted_pairs if self.emitted_pairs else 0.0


def _canon_unit(u: Any) -> str | None:
    return E.UNIT_MAP.get(str(u))


def _param_index(canonical: dict) -> tuple[dict[tuple, str], dict[tuple, str]]:
    """(doc, value, unit) → parametr id. İkinci lüğət sərhəd zondlarınadır."""
    exact: dict[tuple, str] = {}
    probes: dict[tuple, str] = {}
    for p in canonical["parameters"]:
        unit = _canon_unit(p["unit"])
        if not unit:
            continue
        exact.setdefault((p["doc"], E._norm_value(p["value"]), unit), p["id"])
        sup = p.get("supersedes") or {}
        if sup.get("value") is not None:
            su = _canon_unit(sup.get("unit", p["unit"]))
            if su:
                exact.setdefault((p["doc"], E._norm_value(sup["value"]), su), p["id"])
        for pt in (p.get("boundary") or {}).get("points", []):
            probes.setdefault((p["doc"], E._norm_value(pt["value"]), unit), p["id"])
    return exact, probes


def score(canonical: dict, rep: ConflictReport) -> Scoreboard:
    sb = Scoreboard()
    exact, probes = _param_index(canonical)

    def which(view: dict[str, Any]) -> str | None:
        k = (view["doc"], E._norm_value(view["value"]), view["unit"])
        return exact.get(k) or probes.get(k)

    # --- (1) 27 bayat cüt ----------------------------------------------------
    gt_pairs: dict[tuple, dict] = {}
    for p in canonical["parameters"]:
        sup = p.get("supersedes") or {}
        if sup.get("value") is None:
            continue
        unit = _canon_unit(p["unit"])
        su = _canon_unit(sup.get("unit", p["unit"]))
        if not unit or not su:
            continue                     # rəqəmlə ifadə olunmayan bayat dəyər
        key = (p["doc"], frozenset({(E._norm_value(p["value"]), unit),
                                    (E._norm_value(sup["value"]), su)}))
        gt_pairs[key] = p
    # Rəqəmsiz bayat dəyərlər də MƏXRƏCDƏ qalır — alətin çatmadığı yeri
    # gizlətmək ölçünü yalan edərdi.
    sb.stale_total = sum(1 for p in canonical["parameters"]
                         if (p.get("supersedes") or {}).get("value") is not None)
    unreachable = sb.stale_total - len(gt_pairs)

    found_keys: set[tuple] = set()
    sb.emitted_pairs = len(rep.value_conflicts)
    sb.emitted_high_priority = sum(1 for c in rep.value_conflicts if c.priority == "high")
    for rank, c in enumerate(rep.value_conflicts, start=1):
        ka = (c.a["doc"], E._norm_value(c.a["value"]), c.a["unit"])
        kb = (c.b["doc"], E._norm_value(c.b["value"]), c.b["unit"])
        key = (c.a["doc"], frozenset({(ka[1], ka[2]), (kb[1], kb[2])}))
        if c.a["doc"] == c.b["doc"] and key in gt_pairs:
            sb.pair_stale_hit += 1
            if key not in found_keys:
                found_keys.add(key)
                sb.stale_ranks.append(rank)
                p = gt_pairs[key]
                # Bayat tərəf `supersedes.value`-dur; təxmin onu göstərməlidir.
                stale_val = E._norm_value((p["supersedes"])["value"])
                picked = c.a if c.stale_guess == "a" else (c.b if c.stale_guess == "b" else None)
                if picked is None:
                    sb.stale_guess_unknown += 1
                elif E._norm_value(picked["value"]) == stale_val:
                    sb.stale_guess_correct += 1
                else:
                    sb.stale_guess_wrong += 1
            continue
        pa, pb = which(c.a), which(c.b)
        if pa and pb and pa == pb:
            sb.pair_false_positive += 1
            if len(sb.fp_examples) < 6:
                sb.fp_examples.append(f"{pa}: {c.a['value']} {c.a['unit']} "
                                      f"({c.a['section']}) ↔ {c.b['value']} "
                                      f"({c.b['section']})")
        elif pa and pb:
            sb.pair_distinct_params += 1
        else:
            sb.pair_unmapped += 1
    sb.stale_found = len(found_keys)
    sb.stale_missed = sorted(gt_pairs[k]["id"] for k in gt_pairs if k not in found_keys)
    for p in canonical["parameters"]:
        sup = p.get("supersedes") or {}
        if sup.get("value") is None:
            continue
        unit = str(sup.get("unit", p["unit"]))
        if _canon_unit(unit) and _canon_unit(str(p["unit"])):
            continue
        # İKİ FƏRQLİ SƏBƏB, iki fərqli yol xəritəsi:
        #   `rəqəmsiz`  → dəyər ədəd deyil (`no grace period`) — çıxarış qatı
        #   `vahid …`   → ədəddir, amma vahid `extract.UNIT_MAP`-də yoxdur
        #                 (`renewals`, `items`) — lüğət qatı, ucuz düzəliş
        why = ("rəqəmsiz bayat dəyər"
               if not isinstance(sup["value"], (int, float))
               else f"vahid dəstəklənmir: {unit}")
        sb.stale_missed.append(f"{p['id']} ({why})")
    assert unreachable >= 0

    # --- (2) 5 rəqəm toqquşması qrupu ---------------------------------------
    gt_groups = canonical.get("colliding_values") or []
    sb.collision_total = len(gt_groups)
    sb.emitted_collisions = len(rep.collisions)
    emitted = {c.value: c for c in rep.collisions}
    for g in gt_groups:
        v = E._norm_value(g["value"])
        if v in emitted:
            sb.collision_found += 1
        else:
            sb.collision_missed.append(f"{g['value']} {g['unit']}")

    gt_values = {E._norm_value(g["value"]) for g in gt_groups}
    for c in rep.collisions:
        ids = {which(m) for m in c.meanings}
        ids.discard(None)
        if c.value in gt_values or len(ids) >= 2:
            sb.collision_genuine += 1
        else:
            sb.collision_false_positive += 1
    return sb


# ============================================================================
# 8. CLI
# ============================================================================
def _resolve_paths(argv_paths: list[str]) -> list[Path]:
    if not argv_paths:
        return list(E.DEFAULT_DOCS)
    out: list[Path] = []
    for raw in argv_paths:
        p = Path(raw)
        if p.is_dir():
            out.extend(sorted(q for q in p.glob("*.md")
                              if q.name not in {"TRAPS.md", "TOOLS.md", "EXTRACTION.md",
                                                "CONFLICTS.md", "README.md"}))
        else:
            out.append(p)
    return out


def _print_report(rep: ConflictReport, limit: int) -> None:
    print(f"sənəd                 : {len(rep.documents)}")
    print(f"namizəd               : {rep.candidates}")
    print(f"\n[1] EYNİ ANLAYIŞ / FƏRQLİ DƏYƏR : {len(rep.value_conflicts)} namizəd cüt")
    for c in rep.value_conflicts[:limit]:
        side = {"a": "A", "b": "B"}.get(c.stale_guess, "?")
        print(f"  · {c.a['value']} {c.a['unit']} ↔ {c.b['value']} {c.b['unit']}"
              f"  [sim {c.similarity}]  bayat təxmini: {side} ({c.stale_confidence})")
        print(f"      A {c.a['doc']}#{c.a['section']}: «{c.a['quote'][:96]}»")
        print(f"      B {c.b['doc']}#{c.b['section']}: «{c.b['quote'][:96]}»")
    if len(rep.value_conflicts) > limit:
        print(f"  … +{len(rep.value_conflicts) - limit}")

    print(f"\n[2] EYNİ RƏQƏM / FƏRQLİ ANLAYIŞ : {len(rep.collisions)} qrup")
    for c in rep.collisions[:limit]:
        flag = " ⚠ vahid fərqi" if c.cross_unit else ""
        print(f"  · {c.value} ({'/'.join(c.units)}) — {c.n_meanings} məna{flag}")
        for m in c.meanings[:4]:
            mark = " [bayat?]" if m["likely_superseded"] else ""
            print(f"      {m['doc']}#{m['section']}{mark}: «{m['quote'][:88]}»")
    if len(rep.collisions) > limit:
        print(f"  … +{len(rep.collisions) - limit}")

    print(f"\n[3] VERSİYA / TARİX ZƏNCİRİ     : {len(rep.chain_issues)} problem")
    by_code: dict[str, list[ChainIssue]] = defaultdict(list)
    for i in rep.chain_issues:
        by_code[i.code].append(i)
    for code, items in sorted(by_code.items(), key=lambda kv: -len(kv[1])):
        print(f"  {code:<36} {len(items):>3}")
        for it in items[:2]:
            print(f"      {it.doc}#{it.section}: {it.detail}")


def _cmd_report(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="conflicts.py report")
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--out", default=None, help="YAML qaralama faylı")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--threshold", type=float, default=SIM_THRESHOLD)
    ap.add_argument("--same-doc-only", action="store_true",
                    help="yalnız eyni sənəd daxilində cütlər")
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args(argv)

    paths = _resolve_paths(args.paths)
    rep = analyse(paths, threshold=args.threshold,
                  cross_document=not args.same_doc_only)
    _print_report(rep, args.limit)
    if args.out:
        print(f"\nQARALAMA: {write_draft(rep, Path(args.out))}")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(rep.to_payload(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        print(f"JSON: {args.json_out}")
    return 0


def _cmd_score(argv: list[str]) -> int:
    import yaml

    ap = argparse.ArgumentParser(prog="conflicts.py score")
    ap.add_argument("--canonical", default=str(HERE / "CANONICAL.yaml"))
    ap.add_argument("--threshold", type=float, default=SIM_THRESHOLD)
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    canonical = yaml.safe_load(Path(args.canonical).read_text(encoding="utf-8"))
    corpus_dir = Path(args.canonical).resolve().parent
    known = {d["file"] for d in canonical["meta"]["documents"]}
    paths = [corpus_dir / f for f in sorted(known) if (corpus_dir / f).exists()]
    rep = analyse(paths, threshold=args.threshold)
    sb = score(canonical, rep)

    print("=== HESABAT 1 — bayat cüt aşkarlanması ===")
    print(f"reyestrdə bayat cüt   : {sb.stale_total}   "
          f"(CANONICAL parameters[].supersedes; Aurora: TRAPS.md §2.3)")
    print(f"tapıldı               : {sb.stale_found}")
    print(f"RECALL                : {sb.stale_found}/{sb.stale_total} = {sb.stale_recall:.1%}")
    print(f"bayat tərəfin təxmini : doğru {sb.stale_guess_correct} · "
          f"səhv {sb.stale_guess_wrong} · qərarsız {sb.stale_guess_unknown}")
    print(f"təklif edilən cüt     : {sb.emitted_pairs} "
          f"(yüksək prioritet: {sb.emitted_high_priority})")
    if sb.stale_ranks:
        at = " · ".join(f"@{k}: {sum(1 for r in sb.stale_ranks if r <= k)}/{sb.stale_found}"
                        for k in (20, 30, 50, 100))
        print(f"  sıralamada           : {at}   (auditor siyahını yuxarıdan oxuyur)")
    print(f"  bayat cütə düşən      : {sb.pair_stale_hit}")
    print(f"  iki AYRI parametr     : {sb.pair_distinct_params}  (auditor işi — real fərq)")
    print(f"  YALANÇI MÜSBƏT        : {sb.pair_false_positive}  "
          f"({sb.pair_fp_rate:.1%}) — eyni parametrin iki üzü")
    print(f"  xəritələnmədi         : {sb.pair_unmapped}")
    if sb.fp_examples:
        print("  yalançı müsbət nümunə :")
        for e in sb.fp_examples:
            print(f"    - {e}")
    if sb.stale_missed:
        print(f"  TAPILMAYAN            : {', '.join(sb.stale_missed)}")

    print("\n=== HESABAT 2 — rəqəm toqquşması ===")
    print(f"reyestrdə qrup        : {sb.collision_total}   "
          f"(CANONICAL colliding_values; Aurora: TRAPS.md §5)")
    print(f"RECALL                : {sb.collision_found}/{sb.collision_total} = "
          f"{sb.collision_recall:.1%}")
    print(f"təklif edilən qrup    : {sb.emitted_collisions}")
    print(f"  həqiqi toqquşma       : {sb.collision_genuine}")
    print(f"  YALANÇI MÜSBƏT        : {sb.collision_false_positive}")
    if sb.collision_missed:
        print(f"  TAPILMAYAN            : {', '.join(sb.collision_missed)}")

    print("\n=== HESABAT 3 — versiya/tarix zənciri ===")
    by_code: dict[str, int] = defaultdict(int)
    for i in rep.chain_issues:
        by_code[i.code] += 1
    print(f"problem               : {len(rep.chain_issues)}")
    for code, n in sorted(by_code.items(), key=lambda kv: -kv[1]):
        print(f"  {code:<36} {n:>3}")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(asdict(sb), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nJSON: {args.json_out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmds = {"report": _cmd_report, "score": _cmd_score}
    if not argv or argv[0] not in cmds:
        print(__doc__)
        return 2
    return cmds[argv[0]](argv[1:])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

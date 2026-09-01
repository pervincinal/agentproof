#!/usr/bin/env python3
"""Siyasət sənədindən CANONICAL parametr NAMİZƏDLƏRİ çıxarır.

NİYƏ. Auditin ən bahalı hissəsi budur. Aurora korpusundakı 96 parametr TAM ƏL
İLƏ yazıldı; müştəri üçün bu iş sıfırdan təkrarlanır və 14 günlük auditi ~25
günə çıxarır. Bu alət həmin işi **azaldır**, ƏVƏZ ETMİR.

SƏRHƏD — ALƏT QƏRAR VERMİR.
    Ground truth-u maşın "bilə" bilməz: `value: 14` sənəddə həqiqətən 14-dürmü,
    hansı şərtlərdə qüvvədədir, aktivdirmi yoxsa bayatdır — bunlar insanın
    qərarıdır. Alət yalnız NAMİZƏD təklif edir və hər namizədin yanına
    sənəddəki TAM CÜMLƏNİ iqtibas kimi qoyur ki, auditor bir baxışda
    təsdiqləsin və ya atsın.
    Ona görə çıxış `parameters:` deyil, **`parameter_candidates:`** açarındadır
    və `status` / `doc_version` / `applies_when` sahələri BOŞ qalır — onları
    insan doldurur. Çıxış faylı heç vaxt CANONICAL.yaml ola bilməz (yoxlanılır).

TƏKƏR YENİDƏN İXTİRA EDİLMİR. İki mövcud modul yeni istiqamətə yönəldilir:
    * `agentproof/graders/canonical.py` — `analyze()` / `extract_quantities()`
      rəqəm+vahid cütlərini (müddət, faiz, valyuta, çoxdilli) artıq tapır;
    * `target/corpus/anchors.py` — bənd nömrəsi parsinqi (`doc#clause`).
  Burada yalnız siyasət mətninə xas nazik qat əlavə olunur: sənəd baş
  məlumatı, bənd bloklarına bölmə, cümlə iqtibası və sənəd dilində olub
  qrader lüğətində olmayan vahidlər (kq, saat `14:00`, sayılan isimlər,
  `4-7 iş günü` kimi intervallar).

İstifadə:
    python target/corpus/extract.py draft target/corpus/*.md --out draft.yaml
    python target/corpus/extract.py score            # Aurora üzərində recall
    python target/corpus/extract.py score --json report.json

Ölçülmüş recall və tapılmayanların səbəb bölgüsü: `target/corpus/EXTRACTION.md`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Iterator

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from agentproof.graders import canonical as G  # noqa: E402  (rəqəm+vahid motoru)

# Paket yolu ÜSTÜNLÜKLÜDÜR: `import anchors` ilə `target.corpus.anchors` iki
# ayrı modul obyekti yaradır və modul vəziyyəti ikiləşir. Fallback yalnız
# repo kökü sys.path-da olmayan qaçışlar üçündür.
try:  # noqa: E402
    from target.corpus import anchors as A  # bənd nömrəsi qaydaları
    from target.corpus import schema as S   # section_key normalizasiyası
except ImportError:  # pragma: no cover - birbaşa skript qaçışı
    import anchors as A  # type: ignore[no-redef]
    import schema as S  # type: ignore[no-redef]

DEFAULT_DOCS = sorted(
    p for p in HERE.glob("*.md")
    if p.name not in {"TRAPS.md", "TOOLS.md", "EXTRACTION.md"}
)


# ============================================================================
# Sənəd modeli
# ============================================================================
@dataclass(frozen=True)
class Clause:
    """Bir bənd: nömrə, başlıq və mətn sətirləri."""

    key: str            # "2.1", "4", "appendix-a.1"
    label: str          # "§2.1", "Appendix A.1"
    heading: str        # ən yaxın `##` başlığı
    lines: list[str]
    appendix: bool


@dataclass(frozen=True)
class Document:
    file: str
    doc_id: str | None
    version: str | None
    effective_from: str | None
    clauses: list[Clause]


_FRONT_MATTER = {
    "doc_id": re.compile(r"^>\s*\*\*Document ID:\*\*\s*(.+?)\s*$", re.M),
    "version": re.compile(r"^>\s*\*\*Version:\*\*\s*(.+?)\s*$", re.M),
    "effective_from": re.compile(r"^>\s*\*\*Effective from:\*\*\s*(.+?)\s*$", re.M),
}
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")


def _strip_md(line: str) -> str:
    """Markdown bəzəyini atır — bənd nömrəsi `**A.1 ...**` içində gizlənə bilir."""
    return line.replace("**", "").replace("*", "").strip()


def parse_document(path: Path) -> Document:
    """Markdown siyasət sənədini bənd bloklarına bölür.

    Bənd nömrəsi qaydaları `anchors.py`-dən gəlir — lövbər qatı ilə eyni
    bölgü olsun deyə (fərqli parser namizədi başqa bəndə yazardı).
    """
    text = path.read_text(encoding="utf-8")
    meta = {k: (m.group(1) if (m := rx.search(text)) else None)
            for k, rx in _FRONT_MATTER.items()}

    clauses: list[Clause] = []
    heading = ""
    appendix_letter: str | None = None
    cur: Clause | None = None

    def flush() -> None:
        nonlocal cur
        if cur is not None and any(l.strip() for l in cur.lines):
            clauses.append(cur)
        cur = None

    for raw in text.splitlines():
        stripped = raw.strip()
        hm = _HEADING_RE.match(stripped)
        head_body = _strip_md(hm.group(1)) if hm else None

        if hm:
            flush()
            heading = head_body or ""
            am = A.APPENDIX_RE.match(heading)
            if am:
                appendix_letter = am.group(1).upper()
                cur = Clause(f"appendix-{appendix_letter.lower()}",
                             f"Appendix {appendix_letter}", heading, [], True)
                continue
            sm = A.SECTION_RE.match(heading)
            if sm:
                cur = Clause(sm.group("n"), f"§{sm.group('n')}", heading, [], False)
            continue

        line = _strip_md(raw)
        if not line:
            if cur is not None:
                cur.lines.append("")
            continue

        acm = A.APPENDIX_CLAUSE_RE.match(line)
        if acm and appendix_letter and acm.group(1).upper() == appendix_letter:
            flush()
            key = f"appendix-{acm.group(1).lower()}.{acm.group(2)}"
            cur = Clause(key, f"Appendix {acm.group(1).upper()}.{acm.group(2)}",
                         heading, [raw], True)
            continue

        cm = A.CLAUSE_RE.match(line)
        if cm:
            flush()
            key = f"{cm.group('n')}.{cm.group('m')}"
            cur = Clause(key, f"§{key}", heading, [raw], appendix_letter is not None)
            continue

        if cur is None:  # başlıqdan əvvəlki baş məlumat
            continue
        cur.lines.append(raw)

    flush()
    return Document(path.name, meta["doc_id"], meta["version"],
                    meta["effective_from"], clauses)


# ============================================================================
# Cümləyə bölmə
# ============================================================================
#  Nöqtə rəqəmlər arasında (`20.0`, `v3.2`) və `A.1`-də cümlə sonu DEYİL —
#  ona görə bölgü nöqtədən sonra BOŞLUQ tələb edir və rəqəmdən əvvəl gəlməyi
#  qadağan edir.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[^\s])")

#: Cümlənin əvvəlindəki bənd nömrəsi (`2.3 Business days are ...`). ATILMALIDIR:
#: `2.3` + `Business days` rəqəm+vahid kimi oxunur və uydurma namizəd yaradır.
#: Nömrə onsuz da `section` sahəsindədir.
_LEADING_CLAUSE = re.compile(r"^(?:\d+\.\d+|[A-Z]\.\d+|\d+\.)\s+")


def iter_sentences(clause: Clause) -> Iterator[str]:
    """Bəndin cümlələri. Cədvəl sətri və bullet AYRI vahid sayılır.

    Bir cədvəl sətrində bir neçə rəqəm olur (`| 1 | Rank | 14 days |`);
    onları bir "cümlə" kimi vermək iqtibası oxunmaz edir.
    """
    for raw in clause.lines:
        line = _LEADING_CLAUSE.sub("", raw.strip())
        if not line:
            continue
        if line.startswith("|") or line.startswith("- ") or line.startswith("* "):
            yield line
            continue
        for s in _SENTENCE_SPLIT.split(line):
            if s.strip():
                yield s.strip()


# ============================================================================
# Vahid qatı — qrader lüğətinin ÜSTÜNƏ, onu dəyişmədən
# ============================================================================
# `agentproof/graders/canonical.py` agent CAVABLARINI qiymətləndirmək üçün
# qurulub; oradakı vahid lüğətini genişləndirmək qiymətləndirmə semantikasını
# dəyişər. Siyasət MƏTNİNDƏ isə orada olmayan vahidlər var. Onlar burada,
# yalnız çıxarış üçün, əlavə olunur.
_EXTRA_UNIT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("kg", re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s?(?:kg|kilograms?|kilos?)\b")),
    # `utc+04:00` saat DEYİL — zona sürüşməsidir; `+`/`-` lookbehind-a salınıb.
    ("time_of_day", re.compile(r"(?<![\w.:+-])(\d{1,2}:\d{2})(?![\d:])")),
    ("attempts", re.compile(r"(?<![\w.])(\d+)\s+(?:consecutive\s+)?(?:failed\s+)?"
                            r"(?:sign-?in\s+|login\s+)?attempts?\b")),
    ("codes", re.compile(r"(?<![\w.])(\d+)\s+(?:promotional\s+|promo\s+|discount\s+)?codes?\b")),
    ("characters", re.compile(r"(?<![\w.])(\d+)\s+characters?\b")),
]

#: `4-7 business days` → value `[4, 7]`. Kanonik cədvəldə intervallar siyahı
#: kimi saxlanılır; tək rəqəmə yuvarlaqlaşdırmaq sərhəd testini məhv edərdi.
_RANGE_RE = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?)\s?[-–—]\s?(\d+(?:[.,]\d+)?)\s?"
    r"(business days|business day|working days|calendar days|days|day|months|month|"
    r"weeks|week|hours|hour|years|year|kg)\b"
)
_RANGE_UNIT = {
    "business days": "business_day", "business day": "business_day",
    "working days": "business_day", "calendar days": "day", "days": "day", "day": "day",
    "months": "month", "month": "month", "weeks": "week", "week": "week",
    "hours": "hour", "hour": "hour", "years": "year", "year": "year", "kg": "kg",
}


def sentence_quantities(sentence: str) -> list[tuple[str, str]]:
    """Bir cümlədəki (dəyər, vahid) cütləri. Vahidsiz rəqəm ATILIR.

    Vahidsiz rəqəm (`§5`, `day 0`, bənd nömrəsi) parametr namizədi deyil —
    onları saxlamaq namizəd sayını bir neçə dəfə artırır və auditorun
    yoxlama işini alətin qazandırdığından çox edir.
    """
    ct = G.canonical_text(sentence)
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(value: str | None, unit: str | None) -> None:
        if not value or not unit:
            return
        if (value, unit) not in seen:
            seen.add((value, unit))
            out.append((value, unit))

    for m in _RANGE_RE.finditer(ct):
        lo, hi = G._to_value(m.group(1)), G._to_value(m.group(2))
        if lo and hi:
            add(f"{lo}|{hi}", _RANGE_UNIT[m.group(3)])

    for q in G.extract_quantities(sentence):
        if q.unit == "count":       # vahidsiz rəqəm — namizəd deyil
            continue
        add(q.value, q.unit)

    for unit, rx in _EXTRA_UNIT_PATTERNS:
        for m in rx.finditer(ct):
            add(G._to_value(m.group(1)) if unit != "time_of_day" else m.group(1), unit)

    return out


# ============================================================================
# Namizədlər
# ============================================================================
@dataclass
class Candidate:
    """Bir parametr namizədi. `status`/`doc_version`/`applies_when` BOŞDUR."""

    candidate_id: str
    value: Any
    unit: str
    doc: str
    section: str
    status: str = ""          # ← insan doldurur
    doc_version: str = ""     # ← insan doldurur
    applies_when: str = ""    # ← insan doldurur
    source: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.doc, S.section_key(self.section) or self.section,
                _norm_value(self.value), self.unit)


def _norm_value(v: Any) -> str:
    if isinstance(v, list):
        return "|".join(_norm_value(x) for x in v)
    if isinstance(v, bool):
        return str(v).lower()
    s = G._to_value(str(v))
    return s if s is not None else str(v).strip().lower()


_SUPERSEDED_CUE = re.compile(r"\bsupersed|\bno longer in force\b|\bunder v\d|\bwas\b", re.I)


def extract_document(path: Path) -> list[Candidate]:
    doc = parse_document(path)
    out: list[Candidate] = []
    seen: set[tuple[str, str, str, str]] = set()
    for clause in doc.clauses:
        for sentence in iter_sentences(clause):
            in_table = sentence.startswith("|")
            for value, unit in sentence_quantities(sentence):
                cid = f"{doc.file}#{clause.key}#{value}-{unit}"
                cand = Candidate(
                    candidate_id=cid,
                    value=_yaml_value(value),
                    unit=unit,
                    doc=doc.file,
                    section=clause.label,
                    source={
                        "quote": _clean_quote(sentence),
                        "heading": clause.heading,
                        "in_table": in_table,
                        "in_appendix": clause.appendix,
                        # Əlavədəki və "supersed…" işarəli cümlələr çox güman
                        # BAYAT dəyərdir — insan `status`-u ona görə seçir.
                        "likely_superseded": bool(
                            clause.appendix or _SUPERSEDED_CUE.search(sentence)),
                    },
                )
                if cand.key in seen:
                    continue
                seen.add(cand.key)
                out.append(cand)
    return out


def _yaml_value(value: str) -> Any:
    if "|" in value:
        return [_yaml_value(x) for x in value.split("|")]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def _clean_quote(sentence: str) -> str:
    return re.sub(r"\s+", " ", sentence.replace("**", "").strip())


# ============================================================================
# Qaralama çıxışı
# ============================================================================
DRAFT_HEADER = """\
# ============================================================================
# PARAMETR NAMİZƏDLƏRİ — QARALAMA. GROUND TRUTH DEYİL.
# ----------------------------------------------------------------------------
# `target/corpus/extract.py` tərəfindən avtomatik yaradıldı. Alət yalnız
# rəqəm+vahid cütü təklif edir; DƏYƏRİN DOĞRULUĞUNA VƏ ŞƏRTLƏRİNƏ İNSAN
# QƏRAR VERİR. Hər namizədin `source.quote` sahəsində sənəddəki tam cümlə var
# — auditor bir baxışda təsdiqləyir və ya atır.
#
# Açar bilərəkdən `parameters:` DEYİL, `parameter_candidates:`-dir: bu fayl
# birbaşa CANONICAL.yaml kimi istifadə edilə bilməz.
#
# İNSANIN DOLDURACAĞI SAHƏLƏR (hamısı boş gəlir):
#   status        — `active` (həqiqət) yoxsa `superseded` (tələ)?
#   doc_version   — dəyər hansı sənəd versiyasından götürüldü?
#   applies_when  — dəyər HANSI ŞƏRTLƏRDƏ qüvvədədir? (onsuz case şərt
#                   seçməsini deyil, sətir uyğunluğunu ölçür)
# Sonra `boundary`, `supersedes`, `precedence_rank` əlavə olunur.
# Sxem: docs/CANONICAL-SCHEMA.md
# ============================================================================
"""


def write_draft(candidates: Iterable[Candidate], documents: Iterable[Document],
                out: Path) -> Path:
    import yaml

    if out.name == "CANONICAL.yaml":
        raise ValueError(
            "namizədlər CANONICAL.yaml-a yazıla bilməz — insan təsdiqi olmadan "
            "qaralama həqiqət cədvəlinə çevrilməməlidir (başqa ad ver)")
    payload = {
        "meta": {
            "generated_by": "target/corpus/extract.py",
            "status": "DRAFT — awaiting human review",
            "documents": [
                {"file": d.file, "id": d.doc_id, "version": d.version,
                 "effective_from": d.effective_from}
                for d in documents
            ],
        },
        "parameter_candidates": [asdict(c) for c in candidates],
    }
    out.write_text(
        DRAFT_HEADER + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    return out


# ============================================================================
# Recall ölçüsü — Aurora korpusuna qarşı
# ============================================================================
#: Kanonik vahid → çıxarış vahidi. Solda korpus müəllifinin yazdığı ad,
#: sağda `graders/canonical.py`-nin vahid ailəsi.
UNIT_MAP = {
    "days": "day", "business_days": "business_day",
    "business_days_from_dispatch": "business_day", "months": "month",
    "years": "year", "hours": "hour", "minutes": "minute", "weeks": "week",
    "percent": "percent", "kg": "kg", "attempts": "attempts", "codes": "codes",
    "characters": "characters", "time_of_day": "time_of_day",
    "AZN": "azn", "USD": "usd", "EUR": "eur",
}
#: Rəqəmlə ifadə OLUNMAYAN vahidlər — çıxarışın hədəfi deyil, amma
#: məxrəcdən ÇIXARILMIR (96 parametrin hamısı sayılır).
NON_NUMERIC_UNITS = {"boolean", "enum"}


@dataclass
class Miss:
    parameter: str
    doc: str
    section: str
    value: str
    unit: str
    reason: str
    detail: str = ""


@dataclass
class ScoreReport:
    total: int = 0
    hit_clause: int = 0        # düzgün sənəd + düzgün bənd
    hit_doc: int = 0           # düzgün sənəd, bənd fərqli
    hit_corpus: int = 0        # korpusda var, amma başqa sənəddə
    candidates: int = 0
    matched_candidates: int = 0          # aktiv parametrə düşən namizəd
    matched_stale: int = 0               # `supersedes` (tələ) dəyərinə düşən
    matched_boundary: int = 0            # sərhəd zond nöqtəsinə düşən
    misses: list[Miss] = field(default_factory=list)

    @property
    def found(self) -> int:
        return self.hit_clause + self.hit_doc

    @property
    def recall_doc(self) -> float:
        return self.found / self.total if self.total else 0.0

    @property
    def recall_clause(self) -> float:
        return self.hit_clause / self.total if self.total else 0.0

    @property
    def precision(self) -> float:
        """Yalnız aktiv parametrə düşən pay — ən dar oxunuş."""
        return self.matched_candidates / self.candidates if self.candidates else 0.0

    @property
    def useful(self) -> int:
        """Auditorun İŞİNƏ YARAYAN namizəd: aktiv dəyər + tələ + sərhəd nöqtəsi.

        Sərhəd zond nöqtəsi (`149.99`, `14:01`) və əlavədəki bayat dəyər
        `parameters[]`-də yoxdur, amma korpusun real hissəsidir — onları
        "yalançı müsbət" saymaq alətin faydasını olduğundan az göstərir.
        """
        return self.matched_candidates + self.matched_stale + self.matched_boundary

    @property
    def useful_rate(self) -> float:
        return self.useful / self.candidates if self.candidates else 0.0


def score(canonical: dict, candidates: list[Candidate],
          doc_texts: dict[str, str],
          clause_texts: dict[tuple[str, str], str] | None = None) -> ScoreReport:
    """96 kanonik parametrin neçəsini çıxarışın tapdığını ÖLÇÜR."""
    rep = ScoreReport(candidates=len(candidates))

    by_clause: dict[tuple[str, str, str, str], Candidate] = {}
    by_doc: dict[tuple[str, str, str], list[Candidate]] = {}
    by_value: dict[tuple[str, str], list[Candidate]] = {}
    for c in candidates:
        by_clause.setdefault(c.key, c)
        by_doc.setdefault((c.doc, _norm_value(c.value), c.unit), []).append(c)
        by_value.setdefault((_norm_value(c.value), c.unit), []).append(c)

    # Tələ (bayat) dəyərləri və sərhəd zond nöqtələri — `parameters[]`-də
    # yoxdur, amma çıxarışın tapması faydalıdır.
    stale_keys: set[tuple[str, str, str]] = set()
    boundary_keys: set[tuple[str, str, str]] = set()
    for p in canonical["parameters"]:
        unit = UNIT_MAP.get(str(p["unit"]))
        sup = p.get("supersedes") or {}
        if sup.get("value") is not None:
            su = UNIT_MAP.get(str(sup.get("unit", p["unit"])))
            if su:
                stale_keys.add((p["doc"], _norm_value(sup["value"]), su))
        if unit and "boundary" in p:
            for pt in p["boundary"]["points"]:
                boundary_keys.add((p["doc"], _norm_value(pt["value"]), unit))

    matched: set[str] = set()
    for p in canonical["parameters"]:
        rep.total += 1
        doc = p["doc"]
        sec = S.section_key(str(p["section"])) or str(p["section"])
        val = _norm_value(p["value"])
        unit = UNIT_MAP.get(str(p["unit"]))

        if unit is None:
            rep.misses.append(Miss(p["id"], doc, str(p["section"]), val, str(p["unit"]),
                                   "non_numeric" if p["unit"] in NON_NUMERIC_UNITS
                                   else "unit_unsupported"))
            continue

        if (doc, sec, val, unit) in by_clause:
            rep.hit_clause += 1
            matched.add(by_clause[(doc, sec, val, unit)].candidate_id)
            continue
        if (doc, val, unit) in by_doc:
            rep.hit_doc += 1
            hit = by_doc[(doc, val, unit)][0]
            matched.add(hit.candidate_id)
            continue

        rep.misses.append(Miss(p["id"], doc, str(p["section"]), val, str(p["unit"]),
                               *_diagnose(p, val, unit, clause_texts, doc_texts)))

    rep.matched_candidates = len(matched)
    for c in candidates:
        if c.candidate_id in matched:
            continue
        k = (c.doc, _norm_value(c.value), c.unit)
        if k in stale_keys:
            rep.matched_stale += 1
        elif k in boundary_keys:
            rep.matched_boundary += 1
    return rep


_TABLE_LINE = re.compile(r"^\s*\|")

#: Vahidin sənəddə görünə biləcəyi sözlər — "rəqəm var, vahid var, amma
#: bitişik deyil" halını "rəqəm ümumiyyətlə yoxdur" halından ayırmaq üçün.
_UNIT_WORDS = {
    "day": r"days?|calendar days?", "business_day": r"business days?|working days?",
    "month": r"months?|monthly", "year": r"years?", "hour": r"hours?",
    "minute": r"minutes?", "week": r"weeks?", "percent": r"%|percent",
    "azn": r"azn|manat", "kg": r"kg|kilograms?", "attempts": r"attempts?|times|retr",
    "codes": r"codes?", "characters": r"characters?", "time_of_day": r"\d{1,2}:\d{2}",
}
_ZERO_IN_WORDS = re.compile(
    r"\bno\s+\w+|\bnever\b|\bnot available\b|\bcannot be\b|\bthere is no\b", re.I)
_WORD_NUMBER = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|twenty|thirty)\b", re.I)


def _diagnose(p: dict, val: str, unit: str,
              clause_texts: dict[tuple[str, str], str] | None,
              doc_texts: dict[str, str]) -> tuple[str, str]:
    """Tapılmayanın SƏBƏBİNİ təsnif edir — növbəti versiyanın yol xəritəsi.

    Təsnifat KANONİK BƏNDİN mətninə baxır (bütün sənədə yox): parametr məhz
    orada olmalı idi, deməli səbəb də oradadır. Sənəd səviyyəli axtarış kiçik
    rəqəmlərdə (`0`, `1`, `3`) təsadüfi sətir tapıb yanlış diaqnoz qoyurdu.
    """
    doc = p["doc"]
    key = S.section_key(str(p["section"])) or str(p["section"])
    text = (clause_texts or {}).get((doc, key))
    if text is None:
        return "clause_not_parsed", f"{doc}#{key} bənd bloklarında tapılmadı"

    flat = re.sub(r"\s+", " ", text)
    unit_pat = _UNIT_WORDS.get(unit, "")
    has_unit = bool(unit_pat and re.search(unit_pat, flat, re.I))
    digits = [n for n in {val, str(p["value"]),
                          *(str(x) for x in (p["value"] if isinstance(p["value"], list) else []))}
              if re.fullmatch(r"-?\d+(?:\.\d+)?", n)]
    has_digit = any(re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", flat) for n in digits)

    if val in ("0", "0.0") and _ZERO_IN_WORDS.search(flat):
        return "zero_expressed_in_words", flat[:130]
    if isinstance(p["value"], list) and re.search(r"\d+\s*,\s*\d+", flat):
        return "enumerated_list_value", flat[:130]
    if not has_digit and _WORD_NUMBER.search(flat):
        return "number_as_word", flat[:130]
    if has_digit and re.search(rf"(?<![\d.]){re.escape(digits[0])}-[a-z-]+", flat, re.I):
        return "hyphenated_compound_modifier", flat[:130]
    if has_digit and has_unit:
        # Rəqəm vahid sözünə BİTİŞİKdirsə, çıxarışın lüğətində həmin sinonim
        # yoxdur (`3 times` ↔ `attempts`). Aralarında söz varsa (`3 delivery
        # attempts`) problem lüğət yox, naxışın bitişiklik tələbidir.
        adjacent = any(
            re.search(rf"(?<![\d.]){re.escape(n)}\s*[-\s]?(?:{unit_pat})", flat, re.I)
            for n in digits)
        return ("unit_synonym_missing" if adjacent
                else "qualifier_between_number_and_unit"), flat[:130]
    if has_digit and not has_unit:
        return "unit_word_absent_from_clause", flat[:130]
    if _TABLE_LINE.search(text):
        return "table_only", flat[:130]
    if not has_digit:
        return "value_absent_from_clause", flat[:130]
    return "unclassified", flat[:130]


# ============================================================================
# CLI
# ============================================================================
def _load_docs(paths: list[Path]) -> tuple[list[Candidate], list[Document],
                                           dict[str, str], dict[tuple[str, str], str]]:
    cands: list[Candidate] = []
    docs: list[Document] = []
    texts: dict[str, str] = {}
    clause_texts: dict[tuple[str, str], str] = {}
    for p in paths:
        doc = parse_document(p)
        docs.append(doc)
        cands.extend(extract_document(p))
        texts[p.name] = p.read_text(encoding="utf-8")
        for cl in doc.clauses:
            clause_texts[(doc.file, cl.key)] = "\n".join(cl.lines)
    return cands, docs, texts, clause_texts


def _cmd_draft(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="extract.py draft")
    ap.add_argument("paths", nargs="*", default=[str(p) for p in DEFAULT_DOCS])
    ap.add_argument("--out", default="candidates.draft.yaml")
    args = ap.parse_args(argv)
    paths = [Path(p) for p in (args.paths or DEFAULT_DOCS)]
    cands, docs, _, _ = _load_docs(paths)
    out = write_draft(cands, docs, Path(args.out))
    print(f"{len(cands)} namizəd, {len(docs)} sənəd → {out}")
    print("QARALAMA — insan təsdiqi olmadan CANONICAL.yaml-a köçürmə.")
    return 0


def _cmd_score(argv: list[str]) -> int:
    import yaml

    ap = argparse.ArgumentParser(prog="extract.py score")
    ap.add_argument("--canonical", default=str(HERE / "CANONICAL.yaml"))
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    canonical = yaml.safe_load(Path(args.canonical).read_text(encoding="utf-8"))
    known = {d["file"] for d in canonical["meta"]["documents"]}
    paths = [HERE / f for f in sorted(known) if (HERE / f).exists()]
    cands, _, texts, clause_texts = _load_docs(paths)
    rep = score(canonical, cands, texts, clause_texts)

    print(f"sənəd                 : {len(paths)}")
    print(f"namizəd               : {rep.candidates}")
    print(f"kanonik parametr      : {rep.total}")
    print(f"tapıldı (sənəd+bənd)  : {rep.hit_clause}")
    print(f"tapıldı (sənəd, bənd≠): {rep.hit_doc}")
    print(f"RECALL @doc           : {rep.found}/{rep.total} = {rep.recall_doc:.1%}")
    print(f"RECALL @clause        : {rep.hit_clause}/{rep.total} = {rep.recall_clause:.1%}")
    print(f"  aktiv parametrə düşən : {rep.matched_candidates}  ({rep.precision:.1%})")
    print(f"  bayat (tələ) dəyərə   : {rep.matched_stale}")
    print(f"  sərhəd zond nöqtəsinə : {rep.matched_boundary}")
    print(f"  FAYDALI PAY           : {rep.useful}/{rep.candidates} = {rep.useful_rate:.1%}"
          f"  (qalan {rep.candidates - rep.useful} namizədi auditor atır)")
    print(f"tapılmadı             : {len(rep.misses)}")
    print("\nTAPILMAYANLARIN SƏBƏBİ:")
    by_reason: dict[str, list[Miss]] = {}
    for m in rep.misses:
        by_reason.setdefault(m.reason, []).append(m)
    for reason, items in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        print(f"  {reason:<26} {len(items):>3}  "
              f"({', '.join(i.parameter for i in items[:4])}"
              f"{' …' if len(items) > 4 else ''})")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({
                "recall_doc": rep.recall_doc, "recall_clause": rep.recall_clause,
                "precision": rep.precision, "total": rep.total, "found": rep.found,
                "candidates": rep.candidates,
                "misses": [asdict(m) for m in rep.misses],
            }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nJSON: {args.json_out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmds = {"draft": _cmd_draft, "score": _cmd_score}
    if not argv or argv[0] not in cmds:
        print(__doc__)
        return 2
    return cmds[argv[0]](argv[1:])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Kəmiyyət normallaşdırma qatı — səth formasını kanonik formaya salır.

Niyə var: `consistency_at_k` pilotda `24 months` ilə `24-month`-u FƏRQLİ saydı və
cavabdakı təsadüfi tarixləri (`2026-09-01`) "fakt" kimi topladı. Nəticədə grader
semantik fərqi yox, ifadə fərqini ölçdü — yəni O1-i (qeyri-determinizm) ölçə
bilmədi. Bu modul həmin səviyyəni ayırır və AYRICA test olunur
(`graders/tests/test_canonical.py`).

Əsas fikirlər:
  * `24 months` / `24-month` / `24 mo` / `twenty-four months` → `Quantity("24", "month")`
  * `2026-09-01`, `March 2027`, `01.09.2026` → `DateValue` — kəmiyyət DEYİL.
    Tarix qərarın özü deyil, çox vaxt "bugün"dən hesablanmış törəmədir.
  * `ORD-10046` kimi identifikatorlar rəqəm sayılmır.
  * Mətn bəndlərə (clause) bölünür ki, "hansı rəqəm hansı qaydaya aiddir"
    sualına yaxınlıq (proximity) ilə cavab verilə bilsin.

Bu modul şəbəkəyə çıxmır və `inspect_ai` import etmir (STACK.md §6).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal

__all__ = [
    "Quantity",
    "DateValue",
    "Token",
    "Analysis",
    "canonical_text",
    "analyze",
    "extract_quantities",
    "extract_dates",
    "parse_quantity",
    "contains_quantity",
    "numeric_spec",
    "contains_number",
    "cue_matches",
]

TokenKind = Literal["quantity", "date", "word"]


# --------------------------------------------------------------------- tiplər
@dataclass(frozen=True)
class Quantity:
    """Kanonik kəmiyyət: dəyər (mətn kimi, dəqiq) + vahid ailəsi."""

    value: str
    unit: str

    @property
    def key(self) -> str:
        return f"{self.value} {self.unit}"

    def __str__(self) -> str:  # pragma: no cover - sadə deleqasiya
        return self.key


@dataclass(frozen=True)
class DateValue:
    """Kanonik tarix: `YYYY`, `YYYY-MM` və ya `YYYY-MM-DD` (nə qədər məlumdursa)."""

    iso: str

    def __str__(self) -> str:  # pragma: no cover - sadə deleqasiya
        return self.iso


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    text: str
    start: int
    end: int
    quantity: Quantity | None = None
    date: DateValue | None = None


@dataclass(frozen=True)
class Analysis:
    """Bir mətnin kanonik təhlili — offsetlər `text`-ə aiddir."""

    text: str
    tokens: list[Token] = field(default_factory=list)
    clauses: list[tuple[int, int]] = field(default_factory=list)
    """Bəndlər: token indeks aralıqları [start, end). Nöqtə, `;`, tire, mötərizə,
    yeni sətir bənd sərhədidir — vergül DEYİL."""

    @property
    def quantities(self) -> list[Quantity]:
        return [t.quantity for t in self.tokens if t.quantity is not None]

    @property
    def dates(self) -> list[DateValue]:
        return [t.date for t in self.tokens if t.date is not None]

    def span(self, lo: int, hi: int) -> str:
        """[lo, hi) token aralığının kanonik mətn parçası."""
        if lo >= hi or not self.tokens:
            return ""
        lo = max(0, lo)
        hi = min(len(self.tokens), hi)
        if lo >= hi:
            return ""
        return self.text[self.tokens[lo].start : self.tokens[hi - 1].end]


# ------------------------------------------------------------- kanonik mətn
_TRANSLATE = {
    **dict.fromkeys(map(ord, "‐‑‒–—―−"), "-"),
    ord("’"): "'",
    ord("‘"): "'",
    ord("“"): '"',
    ord("”"): '"',
    0x00A0: " ",
    0x202F: " ",
    0x2009: " ",
}


def canonical_text(text: str) -> str:
    """Kiçik hərf, NFKC, tire/dırnaq vahidləşdirilməsi, boşluq sıxılması.

    Yeni sətir QORUNUR — bənd sərhədidir.
    """
    out = unicodedata.normalize("NFKC", text or "")
    out = out.translate(_TRANSLATE)
    out = out.lower()
    out = re.sub(r"[^\S\n]+", " ", out)
    out = re.sub(r"\n+", "\n", out)
    return out.strip()


# ------------------------------------------------------------------ vahidlər
# Sıra vacibdir: uzun forma qısadan əvvəl (`business days` > `days`, `months` > `mo`).
_EN_UNITS: list[tuple[str, list[str]]] = [
    ("business_day", ["business days", "business day", "working days", "working day"]),
    ("month", ["months", "month", "mths", "mth", "mos", "mo"]),
    ("day", ["days", "day"]),
    ("year", ["years", "year", "yrs", "yr"]),
    ("week", ["weeks", "week", "wks", "wk"]),
    ("hour", ["hours", "hour", "hrs", "hr", "h"]),
    ("minute", ["minutes", "minute", "mins", "min"]),
    ("percent", ["percentage points", "percentage point", "percent", "pct"]),
]

# Azərbaycan dilində sözlər şəkilçi alır: `30 gündür`, `24 aylıq`, `15 faizdir`.
# Bağlı şəkilçi siyahısı — `ayrı` (ay+rı) və `ilk` (il+k) YANLIŞ tutulmasın deyə.
_AZ_SUFFIX = (
    r"(?:lıqdır|likdir|luqdur|lükdür|ları|ləri|lıq|lik|luq|lük|dır|dir|dur|dür"
    r"|dan|dən|da|də|lar|lər|ı|i|u|ü|a|ə|ə)?"
)
_AZ_UNITS: list[tuple[str, list[str]]] = [
    ("business_day", ["iş günü", "iş günləri", "işgünü"]),
    ("month", ["ay"]),
    ("day", ["gün"]),
    ("year", ["il"]),
    ("week", ["həftə"]),
    ("hour", ["saat"]),
    ("minute", ["dəqiqə"]),
    ("percent", ["faiz"]),
]

_CURRENCY_SYMBOL = {"$": "usd", "€": "eur", "£": "gbp", "₼": "azn", "₽": "rub", "¥": "jpy"}
_CURRENCY_WORD = {
    "usd": "usd",
    "dollars": "usd",
    "dollar": "usd",
    "eur": "eur",
    "euros": "eur",
    "euro": "eur",
    "gbp": "gbp",
    "pounds": "gbp",
    "pound": "gbp",
    "azn": "azn",
    "manat": "azn",
    "rub": "rub",
    "rubles": "rub",
    "ruble": "rub",
}

_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_ONES = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]

_MONTH_NAMES: dict[str, int] = {}
for _i, _names in enumerate(
    [
        ["january", "jan", "yanvar"],
        ["february", "feb", "fevral"],
        ["march", "mar", "mart"],
        ["april", "apr", "aprel"],
        ["may", "may"],
        ["june", "jun", "iyun"],
        ["july", "jul", "iyul"],
        ["august", "aug", "avqust"],
        ["september", "sept", "sep", "sentyabr"],
        ["october", "oct", "oktyabr"],
        ["november", "nov", "noyabr"],
        ["december", "dec", "dekabr"],
    ],
    start=1,
):
    for _n in _names:
        _MONTH_NAMES[_n] = _i


def _alt(words: list[str]) -> str:
    return "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))


_EN_UNIT_LOOKUP = {form: unit for unit, forms in _EN_UNITS for form in forms}
_AZ_STEM_LOOKUP = sorted(
    ((stem, unit) for unit, stems in _AZ_UNITS for stem in stems),
    key=lambda p: len(p[0]),
    reverse=True,
)

_UNIT_ALT = "|".join(
    [
        _alt([f for _, forms in _EN_UNITS for f in forms]),
        "|".join(f"{re.escape(stem)}{_AZ_SUFFIX}" for stem, _ in _AZ_STEM_LOOKUP),
    ]
)
_CUR_WORD_ALT = _alt(list(_CURRENCY_WORD)) + "|" + f"manat{_AZ_SUFFIX}"
_CUR_SYM_ALT = _alt(list(_CURRENCY_SYMBOL))
_MONTH_ALT = _alt(list(_MONTH_NAMES))
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?"
_NUM_WORD_ALT = (
    "|".join(f"{t}[- ]{o}" for t in _TENS for o in _ONES)
    + "|"
    + _alt(list(_NUM_WORDS))
)
_SIGN = r"(?<![\w.])[+-]?"
# Rəqəmlə vahid arasına düşən müəyyənləşdiricilər: `6 more months`, `2 additional days`.
_MODIFIER = r"(?:\s(?:more|additional|extra|further|full|whole|calendar|əlavə))?"

_MASTER = re.compile(
    "|".join(
        [
            # --- tarixlər (rəqəmlərdən ƏVVƏL gəlməlidir)
            r"(?P<iso>\b\d{4}-\d{1,2}-\d{1,2}\b)",
            r"(?P<ymd>\b\d{4}/\d{1,2}/\d{1,2}\b)",
            r"(?P<mdy>\b\d{1,2}/\d{1,2}/\d{4}\b)",
            r"(?P<dmy>\b\d{1,2}\.\d{1,2}\.\d{4}\b)",
            rf"(?P<mdy_name>\b(?:{_MONTH_ALT})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\s*,?\s+\d{{4}}\b)",
            rf"(?P<dmy_name>\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH_ALT})\.?\s*,?\s+\d{{4}}\b)",
            rf"(?P<my_name>\b(?:{_MONTH_ALT})\.?\s+\d{{4}}\b)",
            # --- identifikatorlar (ORD-10046, covid-19) — rəqəm SAYILMIR
            r"(?P<ident>\b[^\W\d_]{2,}-\d+[\w-]*\b)",
            # --- valyuta
            rf"(?P<cur_pre>(?:{_CUR_SYM_ALT})\s?(?:{_NUM}))",
            rf"(?P<cur_word_pre>\b(?:{_CUR_WORD_ALT})\s(?:{_NUM})\b)",
            rf"(?P<cur_post>{_SIGN}(?:{_NUM})\s?(?:{_CUR_SYM_ALT}|\b(?:{_CUR_WORD_ALT})\b))",
            # --- faiz və vahidli kəmiyyətlər
            rf"(?P<pct>{_SIGN}(?:{_NUM})\s?%)",
            rf"(?P<num_unit>{_SIGN}(?:{_NUM}){_MODIFIER}[\s-]?(?:{_UNIT_ALT})(?![\w]))",
            rf"(?P<word_unit>\b(?:{_NUM_WORD_ALT}){_MODIFIER}[\s-](?:{_UNIT_ALT})(?![\w]))",
            # --- vahidsiz 4 rəqəmli il (2024) — tarixdir, siyasət rəqəmi deyil
            r"(?P<bare_year>\b(?:19|20)\d{2}\b)",
            rf"(?P<num>{_SIGN}(?:{_NUM}))",
            r"(?P<word>[^\W\d_]+(?:[-'][^\W\d_]+)*)",
        ]
    ),
    re.UNICODE,
)

_CLAUSE_BREAKS = set(".!?;:—–\n()[]•|/\\-")


# ------------------------------------------------------------------ parserlər
def _to_value(raw: str) -> str | None:
    """`1,200` → `1200`, `15,5` → `15.5`, `15.0` → `15`. Qərarsızdırsa None."""
    s = raw.strip().replace(" ", "")
    sign = "-" if s.startswith("-") else ""
    s = s.lstrip("+-")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):
        s = s.replace(",", "")
    elif "," in s:
        # min ayırıcısı deyil (3 rəqəm qrupu yoxdur) → onluq vergül
        s = s.replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:  # pragma: no cover - regex bunu buraxmır
        return None
    if d == d.to_integral_value():
        d = d.quantize(Decimal(1))
    else:
        d = d.normalize()
    return f"{sign}{format(d, 'f')}"


_MODIFIER_WORDS = re.compile(r"^(?:more|additional|extra|further|full|whole|calendar|əlavə)\s+")


def _resolve_unit(raw: str) -> str | None:
    s = re.sub(r"\s+", " ", raw.strip().replace("-", " ")).strip()
    s = _MODIFIER_WORDS.sub("", s)
    if s in _EN_UNIT_LOOKUP:
        return _EN_UNIT_LOOKUP[s]
    for stem, unit in _AZ_STEM_LOOKUP:
        if s.startswith(stem):
            return unit
    return None


def _resolve_currency(raw: str) -> str | None:
    s = raw.strip()
    if s in _CURRENCY_SYMBOL:
        return _CURRENCY_SYMBOL[s]
    if s in _CURRENCY_WORD:
        return _CURRENCY_WORD[s]
    if s.startswith("manat"):
        return "azn"
    return None


def _word_number(raw: str) -> str | None:
    s = raw.strip().replace("-", " ")
    parts = s.split()
    if len(parts) == 1 and parts[0] in _NUM_WORDS:
        return str(_NUM_WORDS[parts[0]])
    if len(parts) == 2 and parts[0] in _NUM_WORDS and parts[1] in _NUM_WORDS:
        return str(_NUM_WORDS[parts[0]] + _NUM_WORDS[parts[1]])
    return None


def _iso(year: int, month: int | None = None, day: int | None = None) -> str | None:
    if not 1 <= year <= 9999:
        return None
    if month is None:
        return f"{year:04d}"
    if not 1 <= month <= 12:
        return None
    if day is None:
        return f"{year:04d}-{month:02d}"
    if not 1 <= day <= 31:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _month_from_name(raw: str) -> int | None:
    return _MONTH_NAMES.get(raw.strip().rstrip("."))


def _parse_date(name: str, raw: str) -> DateValue | None:
    if name == "iso":
        y, m, d = (int(p) for p in raw.split("-"))
    elif name == "ymd":
        y, m, d = (int(p) for p in raw.split("/"))
    elif name == "mdy":
        a, b, y = (int(p) for p in raw.split("/"))
        # 13/01/2026 ABŞ formatı ola bilməz → gün/ay kimi oxu
        m, d = (a, b) if a <= 12 else (b, a)
    elif name == "dmy":
        d, m, y = (int(p) for p in raw.split("."))
    elif name in {"mdy_name", "dmy_name", "my_name"}:
        mon = re.search(_MONTH_ALT, raw)
        nums = re.findall(r"\d+", raw)
        if mon is None or not nums:
            return None
        m = _month_from_name(mon.group(0)) or 0
        if name == "my_name":
            y, d = int(nums[-1]), None  # type: ignore[assignment]
        else:
            y = int(nums[-1])
            d = int(nums[0])
        iso = _iso(y, m, d)
        return DateValue(iso) if iso else None
    else:  # bare_year
        iso = _iso(int(raw))
        return DateValue(iso) if iso else None
    iso = _iso(y, m, d)
    return DateValue(iso) if iso else None


def _parse_quantity_match(name: str, raw: str) -> Quantity | None:
    if name == "pct":
        value = _to_value(raw.rstrip("% ").strip())
        return Quantity(value, "percent") if value else None
    if name in {"cur_pre", "cur_word_pre", "cur_post"}:
        num = re.search(_NUM, raw)
        cur_raw = raw[: num.start()] + raw[num.end() :] if num else ""
        value = _to_value(num.group(0)) if num else None
        unit = _resolve_currency(cur_raw.strip())
        return Quantity(value, unit) if value and unit else None
    if name == "num_unit":
        num = re.match(rf"{_SIGN}(?:{_NUM})", raw)
        if not num:
            return None
        value = _to_value(num.group(0))
        unit = _resolve_unit(raw[num.end() :])
        return Quantity(value, unit) if value and unit else None
    if name == "word_unit":
        m = re.match(rf"({_NUM_WORD_ALT}){_MODIFIER}[\s-](.+)$", raw)
        if not m:
            return None
        value = _word_number(m.group(1))
        unit = _resolve_unit(m.group(2))
        return Quantity(value, unit) if value and unit else None
    if name == "num":
        value = _to_value(raw)
        return Quantity(value, "count") if value else None
    return None


# -------------------------------------------------------------------- təhlil
def analyze(text: str) -> Analysis:
    """Mətni kanonik formaya salır və tokenlərə + bəndlərə bölür."""
    ct = canonical_text(text)
    tokens: list[Token] = []
    for m in _MASTER.finditer(ct):
        name = m.lastgroup or ""
        raw = m.group(0)
        if name in {"iso", "ymd", "mdy", "dmy", "mdy_name", "dmy_name", "my_name", "bare_year"}:
            dv = _parse_date(name, raw)
            if dv is not None:
                tokens.append(Token("date", raw, m.start(), m.end(), date=dv))
                continue
            tokens.append(Token("word", raw, m.start(), m.end()))
            continue
        if name in {"word", "ident"}:
            tokens.append(Token("word", raw, m.start(), m.end()))
            continue
        q = _parse_quantity_match(name, raw)
        if q is not None:
            tokens.append(Token("quantity", raw, m.start(), m.end(), quantity=q))
        else:  # pragma: no cover - müdafiə
            tokens.append(Token("word", raw, m.start(), m.end()))

    clauses: list[tuple[int, int]] = []
    start = 0
    for i in range(len(tokens)):
        gap = ct[tokens[i].end : tokens[i + 1].start] if i + 1 < len(tokens) else ""
        if i + 1 == len(tokens) or any(c in _CLAUSE_BREAKS for c in gap):
            clauses.append((start, i + 1))
            start = i + 1
    return Analysis(text=ct, tokens=tokens, clauses=clauses)


def extract_quantities(text: str, unit: str | None = None) -> list[Quantity]:
    """Cavabdakı kəmiyyətlər. Tarixlər DAXİL DEYİL — onlar `extract_dates`-dədir."""
    qs = analyze(text).quantities
    return [q for q in qs if unit is None or q.unit == unit]


def extract_dates(text: str) -> list[DateValue]:
    return analyze(text).dates


def parse_quantity(spec: str) -> Quantity | None:
    """`expect` içindəki `"24 month"` kimi spesifikasiyanı oxuyur.

    Yalnız TƏMİZ kəmiyyət qəbul edir — `"24 months warranty"` üçün None qaytarır
    ki, çağıran tərəf mətn axtarışına qayıtsın.
    """
    a = analyze(spec)
    if len(a.tokens) == 1 and a.tokens[0].quantity is not None:
        return a.tokens[0].quantity
    return None


def contains_quantity(text: str, quantity: Quantity) -> bool:
    return quantity in set(extract_quantities(text))


_BARE_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?")


def numeric_spec(spec: str) -> str | None:
    """`expect` iynəsi TAMAMİLƏ rəqəmdirsə kanonik dəyəri, deyilsə None.

    `"14"` → `"14"`, `"149,99"` → `"149.99"`, `"1,200"` → `"1200"`.
    `"14 calendar days"` / `"невозможен"` / `"20%"` → None — bunlar mətn
    iynəsidir və çağıran tərəf adi alt-sətir axtarışında qalmalıdır.
    """
    s = canonical_text(spec)
    if not _BARE_NUMBER.fullmatch(s):
        return None
    return _to_value(s)


def contains_number(text: str, value: str) -> bool:
    """`value` mətndə MÜSTƏQİL ədəd tokeni kimi varmı.

    Niyə lazımdır (docs/GRADER-AUDIT.md#A-08): `contains_all` alt-sətir
    axtarışıdır, ona görə `"3"` iynəsi `2026-08-1<u>3</u>` tarixinin İÇİNDƏ
    tapılırdı və cavabda cəhd sayı ümumiyyətlə olmasa belə case KEÇİRDİ —
    yalançı yaşıl. Burada `analyze()`-in artıq mövcud ayırması işlədilir:

      * `2026-08-13`, `01.09.2026`, `March 2027` → `DateValue`, kəmiyyət DEYİL;
      * `ORD-10015`, `AG-PRT-660` → identifikator, kəmiyyət DEYİL;
      * `164.00 AZN` → `Quantity("164", "azn")` — dəyəri `164`-dür, `14` deyil.

    Yəni ədəd yalnız öz token sərhədləri daxilində tutulur; vahid nə olursa
    olsun (`14 days`, `14 gün`, `14%`, vahidsiz `14`) uyğunlaşır — iynə vahid
    tələb etmir, sadəcə ədədin FAKTİKİ olaraq deyildiyini tələb edir.
    """
    return any(q.value == value for q in extract_quantities(text))


# ---------------------------------------------------------------- açar sözlər
def _cue_pattern(cue: str) -> re.Pattern[str]:
    cue = canonical_text(cue)
    prefix = cue.endswith("*")
    stem = cue[:-1] if prefix else cue
    body = r"\s+".join(re.escape(p) for p in stem.split())
    tail = "" if prefix else r"(?!\w)"
    return re.compile(rf"(?<!\w){body}{tail}", re.UNICODE)


_CUE_CACHE: dict[str, re.Pattern[str]] = {}


def cue_matches(text: str, cue: str) -> bool:
    """`cue` mətndə varmı. Sonu `*` olan cue prefiks kimi işləyir.

    `"warrant*"` → `warranty`, `warranties`; `"warranty"` → yalnız tam söz.
    """
    if not cue:
        return False
    pat = _CUE_CACHE.get(cue)
    if pat is None:
        pat = _CUE_CACHE[cue] = _cue_pattern(cue)
    return pat.search(text) is not None

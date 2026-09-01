"""Statik HTML audit hesabatı (STACK.md §8.5, AP-012).

    render(record, delta=None, repro=None, ...) -> str        # HTML mətni
    python -m agentproof.report.html reports/full-run-02      # -> index.html
    python -m agentproof.report.html reports/full-run-02 \\
        --audience client --client "Şirkət" --out client.html

Bu fayl **müştəri təhvilinin görünən hissəsidir**: auditin nəticəsi bu səhifə
ilə təhvil verilir. Ona görə üç sərt qayda var.

1. **Xarici asılılıq YOXDUR.** Nə CDN, nə şrift, nə piksel. Səhifə oflayn
   açılır; müştəri datası (case mətnləri, agent cavabları) heç bir üçüncü
   tərəf hostuna sorğu doğurmur. Qrafiklər inline SVG-dir, JS isteğe bağlıdır —
   skript bloklansa da səhifənin BÜTÜN məlumatı görünür.
2. **Gizlətmək mümkün deyil.** Judge kalibrasiyası, reproduksiya təsnifatı və
   baseline müqayisəsi MƏCBURİ bölmələrdir: məlumat yoxdursa bölmə yox olmur,
   açıq xəbərdarlığa çevrilir. "Bölmənin olmaması" auditdə "problem yoxdur"
   kimi oxunur — bu, yol verdiyimiz yeganə şey deyil.
3. **Bəzək yox, sıxlıq.** Sınmış case-in TAM girişi və TAM cavabı səhifədədir;
   əsas dəyər budur — auditi oxuyan mühəndis debug-a bu səhifədən başlayır.

**Auditoriya (AP-039).** Səhifənin iki oxucusu var və `--audience` bayrağı
yalnız DİLİ dəyişir, MƏZMUNU yox:

* `internal` — biz. AP-xxx nömrələri, repo yolları, düzəliş əmrləri qalır.
* `client` — müştəri. Yuxarıdakı daxili izlər çıxarılır, çünki müştərinin
  mühəndisi üçün mənasızdır və hesabatı şifahi tərcüməsiz oxunmaz edir.

Çıxarılan şeylərin siyahısı qısadır və orada **heç bir ölçü nəticəsi yoxdur**:
məhdudiyyət, flaky nisbəti, kalibrasiya rəqəmi, ölçülməyən xərc və "nəyi
ölçmədik" bölməsi hər iki rejimdə eynidir. Müştəri hesabatı daha az DAXİLİdir,
daha az DÜRÜST deyil — auditor kimi satdığımız şey məhz həmin bölmələrdir
(`docs/templates/CLIENT-REPORT.md` §4, §7, §8).

`MANDATORY_SECTIONS` bu qərarı maşınla saxlayır: bölmə səhifədən yox olarsa
`render()` `MandatorySectionMissing` atır — kəsmək cəhdi testi qırmızı edir.

Bu modul `inspect_ai` import ETMİR: hesabat qaçış mühərriki qurulmamış maşında
da render olunmalıdır (`report/normalize.py` Inspect-i bilən yeganə fayldır).
"""

from __future__ import annotations

import argparse
import html as _html
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from agentproof.failure import REASON_HINT, reason_for_response
from agentproof.graders.calibration import MIN_AGREEMENT, MIN_KAPPA, judge_status
from agentproof.report import reproduction as repro_mod
from agentproof.report.pr_comment import headline, model_line
from agentproof.types import CaseResult, RunDelta, RunRecord

TAXONOMY_DOC = Path("docs/FAILURE-TAXONOMY.md")

#: `bva`, `G2`, `R6` ... — taksonomiya kodu formasındakı taqlar.
_TAXONOMY_TAG = re.compile(r"^[RGCSTOL][0-9]{1,2}$")

#: Sınmış case-in mətni kəsilmir, amma səhifəni partlatmamaq üçün hədd var.
MAX_TEXT_CHARS = 20_000

BASELINE_MISSING = (
    "BASELINE YOXDUR — REQRESSİYA YOXLANILMADI. Bu səhifədəki rəqəmlər MÜTLƏQ "
    "dəyərlərdir: hansı case-in bu qaçışda SINDIĞI bilinmir, çünki müqayisə "
    "üçün əvvəlki snapshot verilməyib. «Reqressiya görünmür» ilə «reqressiya "
    "yoxdur» eyni şey deyil."
)

DEFAULT_TITLE = "AgentProof audit hesabatı"


# --------------------------------------------------------------- auditoriya
INTERNAL = "internal"
CLIENT = "client"
AUDIENCES = (INTERNAL, CLIENT)

#: HEÇ BİR rejimdə kəsilə bilməyən bölmələr — `docs/templates/CLIENT-REPORT.md`
#: §4 (ölçmənin öz auditi), §7 (judge), §8 (nəyi ölçmədik) və reproduksiya
#: qapısı. Şablon bunu belə əsaslandırır: «məlumat yoxdursa bölmə SİLİNMİR,
#: başlıq qalır, içi xəbərdarlığa çevrilir». Burada eyni qərar maşınla
#: saxlanılır — bölmə səhifədən yox olarsa `render()` partlayır.
MANDATORY_SECTIONS: tuple[tuple[str, str], ...] = (
    ("repro", "Reproduksiya təsnifatı"),
    ("olcme-audit", "Ölçmənin öz auditi"),
    ("judge", "Judge kalibrasiyası"),
    ("olcmedik", "Nəyi ölçmədik"),
)

MANDATORY_MARK = '<span class="must">⛔ MƏCBURİ BÖLMƏ</span>'


class MandatorySectionMissing(RuntimeError):
    """Məcburi bölmə səhifədə yoxdur — hesabat bu halda dərc olunmur."""


#: `client` rejimində səhifədə qalmamalı olan daxili izlər. Bunlar ölçü
#: nəticəsi deyil, bizim daxili nömrələmə və repo təfərrüatımızdır: müştərinin
#: mühəndisi üçün mənası yoxdur və onları oxumaq üçün şifahi tərcümə lazımdır.
INTERNAL_TRACE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # `GAP-02` kimi dataset taqları AP-xxx DEYİL — ona görə solda hərf/rəqəm olmamalıdır.
    ("daxili tapşırıq nömrəsi", re.compile(r"(?<![A-Za-z0-9])AP-\d{1,4}\b")),
    ("daxili audit kodu", re.compile(r"(?<![A-Za-z0-9-])A-\d{2}\b")),
    (
        "daxili rol adı",
        re.compile(
            r"(?<![\w-])(?:harness-eng|grader-eng|dataset-eng|judge-eng|hunter|scout)(?![\w-])",
            re.I,
        ),
    ),
    ("board istinadı", re.compile(r"board/(?:task\.py|tasks\.json)")),
    (
        "repo yolu",
        re.compile(r"(?<![\w/.-])(?:evals|agentproof|docs|dashboard|pricing|board|target)/[\w./@-]+"),
    ),
    ("daxili əmr", re.compile(r"python\s+-m\s+agentproof[\w.]*|\.venv/bin/python")),
    ("daxili sənəd adı", re.compile(r"FAILURE-TAXONOMY|FINDINGS\.md|STACK\.md|PLAN\.md")),
)

REDACTED = "⟨daxili istinad çıxarıldı⟩"

#: Sübut mətni — case girişi, agent cavabı, tool çağırışı, grader səbəbi —
#: HEÇ VAXT redaktə olunmur. "Müştəri üçün təmizləmək" sübutu dəyişdirmək
#: demək deyil: skanner də, redaktor da yalnız hesabatın ÖZ mətninə toxunur.
_VERBATIM = re.compile(
    r"<pre>.*?</pre>"
    r"|data-case=\"[^\"]*\""
    r"|<(?P<t>td|div|span)[^>]*class=\"[^\"]*reason[^\"]*\"[^>]*>.*?</(?P=t)>",
    re.S,
)


def _split_verbatim(page: str) -> list[tuple[bool, str]]:
    """Səhifəni `(sübutdur?, mətn)` parçalarına böl — sıra qorunur."""
    out: list[tuple[bool, str]] = []
    pos = 0
    for m in _VERBATIM.finditer(page):
        if m.start() > pos:
            out.append((False, page[pos : m.start()]))
        out.append((True, m.group(0)))
        pos = m.end()
    if pos < len(page):
        out.append((False, page[pos:]))
    return out


def find_internal_traces(page: str) -> list[tuple[str, str]]:
    """Səhifədə qalan daxili izlər — `[(izin növü, tapılan mətn), ...]`.

    `client` rejimində bu siyahı BOŞ olmalıdır; test məhz bunu yoxlayır
    (AP-037-də əl ilə `grep` edilirdi).
    """
    found: list[tuple[str, str]] = []
    for verbatim, chunk in _split_verbatim(page):
        if verbatim:
            continue
        for name, rx in INTERNAL_TRACE_PATTERNS:
            found += [(name, m.group(0)) for m in rx.finditer(chunk)]
    return found


def scrub_internal(page: str) -> str:
    """Qalan daxili izləri GÖRÜNƏN nişanla əvəz et (müdafiənin ikinci qatı).

    Əsas təmizlik mənbədədir (hər mətn auditoriyaya görə yazılır); bu funksiya
    yalnız gözdən qaçanı tutur. Silmək yox, `REDACTED` ilə əvəz etmək qərarı
    qəsdəndir: oxucu orada nəyinsə çıxarıldığını görməlidir.
    """
    out: list[str] = []
    for verbatim, chunk in _split_verbatim(page):
        if not verbatim:
            for _, rx in INTERNAL_TRACE_PATTERNS:
                chunk = rx.sub(REDACTED, chunk)
        out.append(chunk)
    return "".join(out)


@dataclass(frozen=True)
class Ctx:
    """Render konteksti: kim üçün yazırıq və hesabatın kimliyi (AP-039)."""

    audience: str = INTERNAL
    client_name: str = ""
    system_name: str = ""
    audit_date: str = ""
    labels: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.audience not in AUDIENCES:
            raise ValueError(f"naməlum auditoriya: {self.audience!r} — {AUDIENCES}")

    @property
    def client(self) -> bool:
        return self.audience == CLIENT

    def pick(self, internal: str, client: str) -> str:
        """Eyni faktın iki ifadəsi — rəqəm yox, DİL seçilir."""
        return client if self.client else internal

    def taxon(self, code: str) -> str:
        """Taksonomiya kodu HEÇ VAXT tək başına göstərilmir (DoD)."""
        name = self.labels.get(code, "")
        return f"{code} · {name}" if name else code


# ------------------------------------------------------------------ köməkçilər
def esc(value: Any) -> str:
    return _html.escape("" if value is None else str(value), quote=True)


def _percentile(values: Sequence[float], p: float) -> float:
    """`normalize.percentile()` ilə eyni tərif.

    Oradan import edilmir, çünki `normalize.py` `inspect_ai`-dan asılıdır və
    hesabat qatı mühərriksiz maşında da render olunmalıdır (yuxarıdakı qayda).
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(round((p / 100.0) * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[idx]


def _fmt_ms(ms: float) -> str:
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms:.0f} ms"


def _clip(text: str, limit: int = MAX_TEXT_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def taxonomy_labels(path: Path = TAXONOMY_DOC) -> dict[str, str]:
    """`docs/FAILURE-TAXONOMY.md` başlıqlarından kod → ad xəritəsi.

    Əl ilə yazılmış siyahı saxlamırıq: taksonomiya sənəddə dəyişəndə hesabatın
    etiketi susmaqla köhnəlməsin.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^###\s+([RGCSTOL][0-9]{1,2})\s+—\s+(.+?)\s*$", line)
        if m:
            # Başlıqdakı ingilis qarşılığı, prioritet nişanı və emoji atılır:
            # "G1 — Siyasət uydurması (Policy fabrication) 🔴 №1" -> "Siyasət uydurması"
            name = re.split(r"\s+\(", m.group(2))[0]
            out[m.group(1)] = re.sub(r"[⚠️🔴`]|№\s*\d+", "", name).strip()
    return out


def load_case_inputs(dataset_path: str | Path) -> dict[str, Any]:
    """`case_id -> input` — sınmış case-in TAM girişi RunRecord-da yoxdur.

    Dataset-i `runner/task.py` ilə yükləmirik: o, Inspect-i import edir.
    Burada yalnız id və giriş lazımdır, ona görə xam jsonl oxunur.
    """
    out: dict[str, Any] = {}
    for line in Path(dataset_path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if "id" in row:
            out[str(row["id"])] = row.get("input", "")
    return out


def load_records(paths: Iterable[str | Path]) -> list[RunRecord]:
    """Qovluq və ya fayl yollarından RunRecord-lar (trend üçün)."""
    records: list[RunRecord] = []
    for raw in paths:
        p = Path(raw)
        files = (
            sorted(q for q in p.glob("*.json") if q.name != "reproduction.json")
            if p.is_dir()
            else [p]
        )
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and "run_id" in data and "results" in data:
                records.append(RunRecord.from_dict(data))
    return records


# ----------------------------------------------------------------- aqreqasiya
@dataclass
class Bucket:
    key: str
    label: str = ""
    passed: int = 0
    failed: int = 0
    skipped: int = 0

    @property
    def graded(self) -> int:
        return self.passed + self.failed

    @property
    def total(self) -> int:
        return self.graded + self.skipped

    @property
    def pass_rate(self) -> float | None:
        """Məxrəc 0-dırsa `None` — 0.0 DEYİL (heç nə ölçülməyib ≠ hamısı sındı)."""
        return (self.passed / self.graded) if self.graded else None


def _bucket(results: Sequence[CaseResult], key_of) -> list[Bucket]:
    buckets: dict[str, Bucket] = {}
    for r in results:
        for key in key_of(r):
            b = buckets.setdefault(key, Bucket(key=key))
            if r.grade.skipped:
                b.skipped += 1
            elif r.grade.passed:
                b.passed += 1
            else:
                b.failed += 1
    return sorted(buckets.values(), key=lambda b: (-b.failed, b.key))


def by_taxonomy(results: Sequence[CaseResult], labels: dict[str, str]) -> list[Bucket]:
    out = _bucket(results, lambda r: [t for t in r.tags if _TAXONOMY_TAG.match(t)])
    for b in out:
        b.label = labels.get(b.key, "")
    untagged = [r for r in results if not any(_TAXONOMY_TAG.match(t) for t in r.tags)]
    if untagged:
        b = Bucket(key="(kodsuz)", label="taksonomiya kodu olan taq yoxdur")
        for r in untagged:
            if r.grade.skipped:
                b.skipped += 1
            elif r.grade.passed:
                b.passed += 1
            else:
                b.failed += 1
        out.append(b)
    return out


def by_grader(results: Sequence[CaseResult]) -> list[Bucket]:
    return _bucket(results, lambda r: [r.grade.grader or "(adsız)"])


def by_severity(results: Sequence[CaseResult]) -> list[Bucket]:
    order = {"high": 0, "medium": 1, "low": 2}
    out = _bucket(results, lambda r: [r.severity or "(yoxdur)"])
    return sorted(out, key=lambda b: order.get(b.key, 9))


def by_tag(results: Sequence[CaseResult], top: int = 25) -> list[Bucket]:
    out = [
        b
        for b in _bucket(results, lambda r: list(r.tags))
        if not _TAXONOMY_TAG.match(b.key)
    ]
    return out[:top]


# --------------------------------------------------------------------- HTML
CSS = """
:root{
  --bg:#fbfbfa; --panel:#fff; --ink:#16161a; --muted:#6b6b76; --line:#e2e2df;
  --pass:#1f7a4d; --fail:#b3261e; --skip:#8a6d1f; --flaky:#a4600a;
  --accent:#2b5fa8; --code-bg:#f4f4f2; --band:#f0f0ee;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#141416; --panel:#1c1c1f; --ink:#e9e9ea; --muted:#9d9da6; --line:#2f2f34;
    --pass:#5fce97; --fail:#ff8a7d; --skip:#e0bb59; --flaky:#f0a24a;
    --accent:#8ab4f0; --code-bg:#232327; --band:#212125;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px 80px}
a{color:var(--accent)}
h1{font-size:22px;margin:24px 0 4px}
h2{font-size:17px;margin:36px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--line)}
h3{font-size:14px;margin:20px 0 8px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.sub{color:var(--muted);font-size:13px}
nav{position:sticky;top:0;z-index:9;background:var(--bg);border-bottom:1px solid var(--line);
  padding:8px 0;margin-bottom:4px;display:flex;flex-wrap:wrap;gap:14px;font-size:12.5px}
nav a{text-decoration:none}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:2px 20px;
  background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px 16px;margin:12px 0}
.meta div{display:flex;justify-content:space-between;gap:12px;padding:3px 0;font-size:12.5px;
  border-bottom:1px dotted var(--line)}
.meta span:first-child{color:var(--muted)}
.meta span:last-child{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;text-align:right}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px 14px}
.tile .k{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.tile .v{font-size:22px;font-weight:600;margin-top:4px;font-variant-numeric:tabular-nums}
.tile .n{font-size:11.5px;color:var(--muted);margin-top:2px}
.pass{color:var(--pass)} .fail{color:var(--fail)} .skip{color:var(--skip)} .flakyc{color:var(--flaky)}
.warn{border:2px solid var(--fail);border-radius:6px;padding:12px 16px;margin:12px 0;
  background:var(--panel);font-weight:600;color:var(--fail)}
.warn .body{font-weight:400;color:var(--ink);margin-top:6px}
.note{border-left:3px solid var(--line);padding:8px 14px;margin:12px 0;color:var(--muted);font-size:13px}
.ok{border:1px solid var(--pass);border-radius:6px;padding:10px 16px;margin:12px 0;background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}
th,td{text-align:left;padding:6px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
tbody tr:hover{background:var(--band)}
.bar{position:relative;height:9px;border-radius:2px;background:var(--line);min-width:90px;overflow:hidden}
.bar i{position:absolute;inset:0 auto 0 0;background:var(--pass)}
.bar i.low{background:var(--fail)}
.bar i.mid{background:var(--flaky)}
.scroll{overflow-x:auto}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
pre{background:var(--code-bg);border:1px solid var(--line);border-radius:4px;padding:10px 12px;
  white-space:pre-wrap;word-break:break-word;font-size:12.5px;margin:6px 0;max-height:520px;overflow:auto}
details{background:var(--panel);border:1px solid var(--line);border-radius:6px;margin:8px 0;padding:0}
details>summary{cursor:pointer;padding:9px 14px;font-size:13px;list-style:none;display:flex;
  flex-wrap:wrap;gap:10px;align-items:baseline}
details>summary::-webkit-details-marker{display:none}
details>summary::before{content:"▸";color:var(--muted)}
details[open]>summary::before{content:"▾"}
details>.inner{padding:2px 14px 14px;border-top:1px solid var(--line)}
.cid{font-family:ui-monospace,Menlo,monospace;font-weight:600}
.pill{display:inline-block;font-size:11px;padding:1px 7px;border-radius:9px;border:1px solid var(--line);
  color:var(--muted);white-space:nowrap}
.pill.sev-high{border-color:var(--fail);color:var(--fail)}
.pill.cls-flaky{border-color:var(--flaky);color:var(--flaky)}
.pill.cls-stable-fail{border-color:var(--fail);color:var(--fail)}
.pill.cls-stable-pass{border-color:var(--pass);color:var(--pass)}
.reason{color:var(--fail);font-size:12.5px}
.must{font-size:11px;font-weight:600;letter-spacing:.03em;color:var(--fail);
  border:1px solid var(--fail);border-radius:9px;padding:1px 8px;margin-left:8px;
  white-space:nowrap;vertical-align:middle}
.why{border-left:3px solid var(--accent);background:var(--panel);padding:10px 14px;margin:10px 0;
  font-size:12.5px;color:var(--muted)}
.why b{color:var(--ink)}
td.dir{white-space:nowrap;font-weight:600}
.field{margin-top:12px}
.field>.lbl{font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);
  margin-bottom:3px}
.turn{border-left:2px solid var(--line);padding-left:10px;margin:8px 0}
svg{max-width:100%;height:auto;display:block}
.filter{margin:10px 0}
.filter input{width:100%;max-width:420px;padding:7px 10px;border:1px solid var(--line);border-radius:5px;
  background:var(--panel);color:var(--ink);font-size:13px}
footer{margin-top:48px;padding-top:14px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}
"""

JS = """
(function(){
  var box=document.getElementById('case-filter');
  if(!box) return;
  var items=[].slice.call(document.querySelectorAll('[data-case]'));
  var count=document.getElementById('case-filter-count');
  box.addEventListener('input',function(){
    var q=box.value.trim().toLowerCase(), shown=0;
    items.forEach(function(el){
      var hit=!q||el.getAttribute('data-case').indexOf(q)>=0;
      el.style.display=hit?'':'none'; if(hit) shown++;
    });
    if(count) count.textContent=shown+' / '+items.length+' case göstərilir';
  });
})();
"""


def _bar(rate: float | None) -> str:
    if rate is None:
        return '<span class="sub">n/a</span>'
    cls = "" if rate >= 0.9 else ("mid" if rate >= 0.7 else "low")
    return (
        f'<div class="bar" title="{rate:.1%}"><i class="{cls}" '
        f'style="width:{max(rate * 100, 1):.1f}%"></i></div>'
    )


def _tile(key: str, value: str, note: str = "", cls: str = "") -> str:
    return (
        f'<div class="tile"><div class="k">{esc(key)}</div>'
        f'<div class="v {cls}">{value}</div>'
        + (f'<div class="n">{esc(note)}</div>' if note else "")
        + "</div>"
    )


def _cost_tile_sub(totals: dict) -> str:
    """Xərc plitəsinin alt sətri: yandırılan və ÖLÇÜLMƏYƏN hissə (AP-026).

    "bütün case, bütün təkrar" yazısı yanlış idi: sınan cəhdlərin xərci
    ümumiyyətlə sayılmırdı və rəqəm həqiqətdən aşağı çıxırdı.
    """
    wasted = float(totals.get("wasted_cost_usd", 0.0) or 0.0)
    cov = totals.get("cost_coverage") or {}
    unmeasured = int(cov.get("unmeasured_attempts", 0) or 0)
    parts = ["uğurlu cəhdlər", f"+${wasted:.2f} yandırılmış"]
    if unmeasured:
        parts.append(f"{unmeasured} cəhd ÖLÇÜLMƏDİ (naməlum, sıfır deyil)")
    return " · ".join(parts)


def _bucket_table(buckets: Sequence[Bucket], head: str) -> str:
    if not buckets:
        return '<p class="sub">məlumat yoxdur</p>'
    rows = []
    for b in buckets:
        rate = b.pass_rate
        rows.append(
            "<tr>"
            f"<td><b>{esc(b.key)}</b>"
            + (f'<div class="sub">{esc(b.label)}</div>' if b.label else "")
            + "</td>"
            f'<td class="num">{b.total}</td>'
            f'<td class="num pass">{b.passed}</td>'
            f'<td class="num {"fail" if b.failed else ""}">{b.failed}</td>'
            f'<td class="num {"skip" if b.skipped else ""}">{b.skipped}</td>'
            f'<td class="num">{"n/a" if rate is None else f"{rate:.0%}"}</td>'
            f"<td>{_bar(rate)}</td></tr>"
        )
    return (
        '<div class="scroll"><table><thead><tr>'
        f'<th>{esc(head)}</th><th class="num">case</th><th class="num">keçdi</th>'
        '<th class="num">sındı</th><th class="num">skip</th>'
        '<th class="num">keçmə</th><th>&nbsp;</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _histogram_svg(values: Sequence[float], bins: int = 24, unit: str = "s") -> str:
    """Gecikmə/xərc paylanması — inline SVG, kənar kitabxana yoxdur."""
    if not values:
        return '<p class="sub">ölçü yoxdur</p>'
    lo, hi = min(values), max(values)
    if hi <= lo:
        hi = lo + 1e-9
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / (hi - lo) * bins), bins - 1)
        counts[idx] += 1
    top = max(counts) or 1
    w, h, pad = 760, 150, 26
    bw = (w - 2 * pad) / bins
    bars = []
    for i, c in enumerate(counts):
        bh = (c / top) * (h - 2 * pad)
        x = pad + i * bw
        bars.append(
            f'<rect x="{x:.1f}" y="{h - pad - bh:.1f}" width="{max(bw - 1.5, 1):.1f}" '
            f'height="{bh:.1f}" fill="currentColor" opacity="0.72"><title>'
            f"{lo + (hi - lo) * i / bins:.2f}–{lo + (hi - lo) * (i + 1) / bins:.2f} {unit}: "
            f"{c} case</title></rect>"
        )
    return (
        f'<svg viewBox="0 0 {w} {h}" role="img" style="color:var(--accent)" '
        f'aria-label="paylanma histoqramı">'
        + "".join(bars)
        + f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" '
        'stroke="currentColor" opacity="0.35"/>'
        f'<text x="{pad}" y="{h - 8}" font-size="11" fill="currentColor" opacity="0.7">'
        f"{lo:.2f} {unit}</text>"
        f'<text x="{w - pad}" y="{h - 8}" font-size="11" text-anchor="end" '
        f'fill="currentColor" opacity="0.7">{hi:.2f} {unit}</text>'
        f'<text x="{pad}" y="14" font-size="11" fill="currentColor" opacity="0.7">'
        f"ən çox {top} case / sütun</text></svg>"
    )


def _trend_svg(points: Sequence[tuple[str, float]]) -> str:
    if len(points) < 2:
        return ""
    w, h, pad = 760, 180, 34
    n = len(points)
    ys = [p[1] for p in points]
    lo, hi = min(ys), max(ys)
    if hi - lo < 0.05:
        lo, hi = max(0.0, lo - 0.05), min(1.0, hi + 0.05)
    span = (hi - lo) or 1.0
    coords = [
        (
            pad + i * (w - 2 * pad) / (n - 1),
            h - pad - (v - lo) / span * (h - 2 * pad),
        )
        for i, (_, v) in enumerate(points)
    ]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(coords))
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="currentColor">'
        f"<title>{esc(points[i][0])}: {points[i][1]:.1%}</title></circle>"
        for i, (x, y) in enumerate(coords)
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" role="img" style="color:var(--accent)" '
        f'aria-label="keçmə dərəcəsi trendi">'
        f'<path d="{path}" fill="none" stroke="currentColor" stroke-width="2"/>{dots}'
        f'<text x="4" y="{pad}" font-size="11" fill="currentColor" opacity="0.7">{hi:.0%}</text>'
        f'<text x="4" y="{h - pad}" font-size="11" fill="currentColor" opacity="0.7">{lo:.0%}</text>'
        f'<text x="{pad}" y="{h - 8}" font-size="11" fill="currentColor" opacity="0.7">'
        f"{esc(points[0][0])}</text>"
        f'<text x="{w - pad}" y="{h - 8}" font-size="11" text-anchor="end" fill="currentColor" '
        f'opacity="0.7">{esc(points[-1][0])}</text></svg>'
    )


# ----------------------------------------------------------------- bölmələr
def _section_meta(
    record: RunRecord, repro: repro_mod.ReproductionReport | None, ctx: Ctx
) -> str:
    t = record.totals
    check = t.get("model_check") or {}
    rows = [
        # `run_id` və qovluq adı hesabatın hər rəqəminin geri izlənməsi üçündür —
        # şablon (§başlıq) bunları müştəri versiyasında da saxlamağı tələb edir.
        ("qaçış (run_id)", record.run_id),
        ("sınanan sistem", ctx.system_name or f"{record.target}@{record.target_version or '?'}"),
        ("hədəfin modeli", model_line(record)),
        ("başlama", record.started_at),
        ("dataset hash", record.dataset_hash or "?"),
        ("case sayı", str(t.get("n_cases", len(record.results)))),
        (
            ctx.pick("təkrar (--repeat)", "hər case üçün təkrar"),
            str(repro.repeats) if repro else "bilinmir",
        ),
        ("izolyasiya lane", str(t.get("lanes", "?"))),
        ("çoxnövbəli case", str(t.get("multi_turn_cases", 0))),
        ("qiymət cədvəli", f"{t.get('price_table_as_of', '?')} · dərəcə {t.get('priced_on', '?')}"),
        ("model yoxlaması", check.get("status", "yoxlanılmayıb")),
        ("hesabat", datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")),
    ]
    if ctx.client:
        rows.insert(0, ("sifarişçi", ctx.client_name or "göstərilməyib"))
        rows.insert(2, ("audit tarixi", ctx.audit_date or record.started_at[:10] or "?"))
    return '<div class="meta">' + "".join(
        f"<div><span>{esc(k)}</span><span>{esc(v)}</span></div>" for k, v in rows
    ) + "</div>"


def _section_summary(
    record: RunRecord, repro: repro_mod.ReproductionReport | None
) -> str:
    t = record.totals
    graded = int(t.get("n_graded", 0))
    rate = float(t.get("pass_rate", 0.0))
    tiles = [
        _tile(
            "keçmə dərəcəsi",
            f"{rate:.1%}" if graded else "n/a",
            f"{t.get('n_passed', 0)} / {graded} qiymətləndirilən",
            "pass" if rate >= 0.9 else ("flakyc" if rate >= 0.7 else "fail"),
        ),
        _tile("sınan", str(t.get("n_failed", 0)), "məzmun uğursuzluğu", "fail"),
        _tile(
            "skipped",
            str(t.get("n_skipped", 0)),
            "qiymətləndirilə bilmədi — səssiz keçmə DEYİL",
            "skip" if t.get("n_skipped") else "",
        ),
        _tile(
            "xərc",
            f"${float(t.get('cost_usd', 0.0)):.2f}",
            _cost_tile_sub(t),
            "skip" if (t.get("cost_coverage") or {}).get("status") == "unmeasured" else "",
        ),
        _tile(
            "gecikmə",
            _fmt_ms(float(t.get("p95_latency_ms", 0.0))),
            f"p95 · p50 {_fmt_ms(float(t.get('p50_latency_ms', 0.0)))}",
        ),
    ]
    if repro is not None and repro.classifiable:
        fr = repro.flaky_rate
        tiles.append(
            _tile(
                "flaky nisbəti",
                "n/a" if fr is None else f"{fr:.1%}",
                f"{repro.counts[repro_mod.FLAKY]} / {repro.n_classified} təsnif olunmuş",
                "fail" if repro.flaky_alarm else "pass",
            )
        )
    else:
        tiles.append(_tile("flaky nisbəti", "ÖLÇÜLMƏDİ", "təkrar qaçışı yoxdur", "fail"))
    return '<div class="tiles">' + "".join(tiles) + "</div>"


def _section_baseline(record: RunRecord, delta: RunDelta | None, ctx: Ctx) -> str:
    out = ['<h2 id="baseline">2 · Baseline müqayisəsi</h2>']
    if delta is None:
        fix = ctx.pick(
            "Qoşmaq üçün: <code>python evals/run.py … "
            "--baseline evals/baselines/&lt;hədəf&gt;@&lt;versiya&gt;.json "
            "--fail-on-regression</code>",
            "Bu auditə əvvəlki qaçışın snapshot-u verilməyib. Reqressiya iddiası "
            "yalnız eyni dataset üzərindəki iki qaçış müqayisə olunanda mümkündür; "
            "bu səhifədəki rəqəmlər «əvvəlkindən pis/yaxşı» yox, «bu qaçışda belədir» "
            "kimi oxunmalıdır.",
        )
        out.append(f'<div class="warn">⚠️ {esc(BASELINE_MISSING)}<div class="body">{fix}</div></div>')
        return "".join(out)
    out.append(f'<p><b>{esc(headline(delta))}</b></p>')
    groups = [
        ("🔴 Sındı", delta.broken, "fail"),
        ("🟢 Düzəldi", delta.fixed, "pass"),
        ("🟡 Flaky (reqressiya sayılmır)", delta.flaky, "flakyc"),
        ("Hələ də sınıq", delta.still_failing, ""),
        ("Yeni case", delta.new_cases, ""),
        ("Silinmiş case", delta.removed_cases, ""),
    ]
    out.append('<div class="tiles">')
    for label, ids, cls in groups:
        out.append(_tile(label, str(len(ids)), ", ".join(ids[:4]), cls))
    out.append("</div>")
    if delta.broken_high_severity:
        out.append(
            '<div class="warn">high severity case sındı: '
            f"{esc(', '.join(delta.broken_high_severity))}</div>"
        )
    return "".join(out)


def _section_reproduction(repro: repro_mod.ReproductionReport | None, ctx: Ctx) -> str:
    out = [f'<h2 id="repro">3 · Reproduksiya təsnifatı{MANDATORY_MARK}</h2>']
    if repro is None:
        fix = ctx.pick(
            "Qoşmaq üçün: <code>python evals/reproduce.py &lt;qaçış qovluğu&gt;</code> "
            "(və ya <code>--repro</code> ilə hazır JSON ver).",
            "Təsnifat üçün hər case-in bir neçə dəfə qaçırılması lazımdır; bu qaçışda "
            "belə bir təkrar dəsti yoxdur.",
        )
        out.append(
            '<div class="warn">⚠️ REPRODUKSİYA TƏSNİFATI YOXDUR — hər case yalnız '
            "BİR dəfə ölçülüb sayılmalıdır."
            '<div class="body">Bu səhifədəki heç bir uğursuzluq «sabit» deyil: '
            f"təkrarlanan uğursuzluqla bir dəfəlik hadisə ayrılmayıb. {fix}</div></div>"
        )
        return "".join(out)
    if not repro.classifiable:
        out.append(
            f'<div class="warn">⚠️ TƏSNİFAT APARILMADI<div class="body">'
            f"{esc(repro.notice)}</div></div>"
        )
        return "".join(out)

    head = repro_mod.flaky_headline(repro)
    box = "warn" if repro.flaky_alarm else "ok"
    out.append(f'<div class="{box}">{esc(head)}</div>')
    if repro.flaky_alarm:
        out.append(
            '<div class="note">Flaky həddi aşılıb: bu qaçışda tək ədəd şəklində '
            "verilən keçmə dərəcəsi təkrar qaçışda təkrarlanmaya bilər. Reqressiya "
            "qapısı flaky case-ləri reqressiya SAYMIR, amma ölçmənin dəqiqliyi bu "
            "nisbətlə məhdudlaşır.</div>"
        )
    labels = {
        repro_mod.STABLE_PASS: "hər cəhddə keçdi",
        repro_mod.STABLE_FAIL: "hər cəhddə EYNİ səbəblə sındı — YALNIZ bu səbət dərc olunur",
        repro_mod.UNSTABLE_FAIL: "hər cəhddə sındı, amma fərqli səbəblərlə — dərc olunmur",
        repro_mod.FLAKY: "qarışıq nəticə — dərc olunmur",
        repro_mod.INCOMPLETE: "cəhdlərin bir hissəsi ölçülmədi",
        repro_mod.SKIPPED: "heç bir cəhd qiymətləndirilmədi",
    }
    counts = repro.counts
    total = len(repro.verdicts) or 1
    rows = "".join(
        "<tr>"
        f'<td><span class="pill cls-{esc(name)}">{esc(name)}</span></td>'
        f'<td class="num">{counts.get(name, 0)}</td>'
        f'<td class="num">{counts.get(name, 0) / total:.0%}</td>'
        f"<td>{esc(labels[name])}</td></tr>"
        for name in labels
    )
    out.append(
        '<div class="scroll"><table><thead><tr><th>təsnifat</th><th class="num">case</th>'
        '<th class="num">pay</th><th>mənası</th></tr></thead><tbody>'
        + rows
        + "</tbody></table></div>"
    )
    # AP-042: bir neçə qaçış birləşibsə, əvəz olunan nəticələr case sayına
    # DAXİL DEYİL — amma hesabatdan da silinmir.
    if repro.n_superseded:
        by_case = len({e.case_id for e in repro.superseded})
        rows = "".join(
            "<tr>"
            f'<td class="cid">{esc(e.case_id)}</td>'
            f"<td>{esc(e.origin.label)}</td>"
            f"<td>{esc(e.superseded_by.label)}</td></tr>"
            for e in repro.superseded
        )
        out.append(
            f'<div class="box ok"><b>Əvəz olunmuş nəticə: {repro.n_superseded}</b> '
            f"({by_case} case) — eyni case bir neçə qaçışda ölçülüb, yuxarıdakı "
            "təsnifat ƏN SON qaçışa görədir. Əvvəlki nəticə silinmir:"
            "<details><summary>siyahı</summary>"
            '<div class="scroll"><table><thead><tr><th>case</th><th>əvəz olunan qaçış</th>'
            "<th>əvəz edən qaçış</th></tr></thead><tbody>"
            + rows
            + "</tbody></table></div></details></div>"
        )
    for warning in repro.warnings:
        out.append(f'<div class="box warn">Birləşmə xəbərdarlığı: {esc(warning)}</div>')

    flaky_cases = repro.by_class(repro_mod.FLAKY)
    if flaky_cases:
        rows = "".join(
            "<tr>"
            f'<td class="cid">{esc(v.case_id)}</td>'
            f'<td><span class="pill sev-{esc(v.severity)}">{esc(v.severity)}</span></td>'
            f"<td>{esc(v.grader)}</td>"
            f'<td class="num">{v.n_passed}/{len(v.graded) or v.n_attempts}</td>'
            f'<td class="reason">{esc((v.reason_variants or [v.note or ""])[0])}</td></tr>'
            for v in flaky_cases
        )
        out.append(
            f"<details><summary>Flaky case-lərin siyahısı ({len(flaky_cases)}) — "
            "dərc olunmur, amma gizlədilmir</summary>"
            '<div class="inner scroll"><table><thead><tr><th>case</th><th>severity</th>'
            '<th>grader</th><th class="num">keçdi</th><th>səbəb (ilk variant)</th>'
            "</tr></thead><tbody>" + rows + "</tbody></table></div></details>"
        )
    return "".join(out)


def _section_judge(record: RunRecord, ctx: Ctx) -> str:
    """MƏCBURİ bölmə — judge işlədilməyibsə də görünür (DoD, JUDGE-CALIBRATION §6)."""
    status = record.totals.get("judge")
    if not isinstance(status, dict):
        status = judge_status(r.grade.grader for r in record.results)

    out = [f'<h2 id="judge">7 · Judge kalibrasiyası{MANDATORY_MARK}</h2>']
    if not status.get("used"):
        out.append(
            '<div class="ok"><b>Bu qaçışda LLM-as-judge grader-i İŞLƏDİLMƏYİB.</b>'
            '<div class="sub" style="margin-top:6px">Bütün verdiktlər determinist '
            "grader-lərdən gəlir (regex, ifadə, tool çağırışı, retrieval) — yəni "
            "hesabatın heç bir rəqəmi model rəyindən asılı deyil və oflayn yenidən "
            "hesablana bilər. Judge case-ləri əlavə olunarsa bu bölmə uyğunluq, "
            "Cohen's κ və n rəqəmlərini göstərməyə borcludur.</div></div>"
        )
        return "".join(out)

    graders = ", ".join(f"<code>{esc(g)}</code>" for g in status.get("graders", []))
    if not status.get("calibrated"):
        fix = ctx.pick(
            "Düzəliş: <code>python evals/calibration/run_calibration.py</code>",
            "Qayda: kalibrasiya rəqəmi (insan etiketi ilə uyğunluq və Cohen's κ) "
            "olmadan judge verdikti dərc olunmur — bu qaçışda judge-dan asılı "
            "nəticələr tapıntı kimi təqdim edilə bilməz.",
        )
        out.append(
            f'<div class="warn">⚠️ KALİBRASİYA EDİLMƏMİŞ JUDGE — NƏTİCƏ MÜDAFİƏ '
            f'OLUNMUR<div class="body">{esc(status.get("warning", ""))}<br>'
            f"Judge grader-ləri: {graders}<br>{fix}</div></div>"
        )
        return "".join(out)

    agreement = float(status.get("agreement", 0.0))
    kappa = float(status.get("kappa", 0.0))
    ok = bool(status.get("passed"))
    out.append(
        '<div class="tiles">'
        + _tile(
            "insan ilə uyğunluq",
            f"{agreement:.1%}",
            f"hədd ≥ {MIN_AGREEMENT:.0%}",
            "pass" if agreement >= MIN_AGREEMENT else "fail",
        )
        + _tile(
            "Cohen's κ",
            f"{kappa:.3f}",
            f"{status.get('kappa_interpretation', '')} · hədd ≥ {MIN_KAPPA:.2f}",
            "pass" if kappa >= MIN_KAPPA else "fail",
        )
        + _tile("n (etiketli nümunə)", str(status.get("n", 0)), "insan etiketi")
        + _tile(
            "qapı",
            "KEÇDİ" if ok else "BLOKLANDI",
            status.get("rubric", ""),
            "pass" if ok else "fail",
        )
        + "</div>"
    )
    out.append(
        f'<p class="sub">{esc(status.get("summary", ""))} · judge modeli '
        f'<code>{esc(status.get("judge_model", "?"))}</code> · etiket dəsti '
        f'<code>{esc(str(status.get("labels_sha256", ""))[:12])}</code> · '
        f"judge grader-ləri: {graders}</p>"
    )
    if status.get("dry_run"):
        out.append(
            '<div class="warn">DRY-RUN KALİBRASİYASI — sabit verdikt verən null '
            "model işlədilib. Bu rəqəmlər qiymətləndirmə kimi istifadə OLUNA BİLMƏZ."
            "</div>"
        )
    for reason in status.get("blocking_reasons", []) or []:
        out.append(f'<div class="warn">{esc(reason)}</div>')
    return "".join(out)


def _section_categories(record: RunRecord, ctx: Ctx) -> str:
    res = record.results
    head = ctx.pick(
        "Uğursuzluq rejimi (FAILURE-TAXONOMY kodu)",
        "Uğursuzluq rejimi (kod və adı)",
    )
    return (
        '<h2 id="kateqoriya">5 · Kateqoriya üzrə keçmə dərəcəsi</h2>'
        '<p class="sub">Bir case bir neçə taqda görünə bilər — sətir cəmləri '
        "case sayından böyük ola bilər. «keçmə» məxrəci yalnız qiymətləndirilən "
        "(skip olmayan) case-lərdir.</p>"
        f"<h3>{esc(head)}</h3>"
        + _bucket_table(by_taxonomy(res, ctx.labels), "kod")
        + "<h3>Grader</h3>"
        + _bucket_table(by_grader(res), "grader")
        + "<h3>Severity</h3>"
        + _bucket_table(by_severity(res), "severity")
        + "<h3>Mövzu taqları (ən çox sınan 25)</h3>"
        + _bucket_table(by_tag(res), "taq")
    )


def _cost_split_note(record: RunRecord) -> str:
    """Uğurlu / yandırılan / ölçülməyən xərc — auditin əsas sualı (AP-026).

    "Audit sizə nə qədər başa gəlir?" sualına "təxminən" cavabı qəbuledilməzdir;
    "$X ölçüldü, N cəhd ölçülmədi" isə dürüst cavabdır.
    """
    t = record.totals
    wasted = float(t.get("wasted_cost_usd", 0.0) or 0.0)
    cov = t.get("cost_coverage") or {}
    if not cov and wasted == 0.0:
        return ""
    rows = [
        ("uğurlu cəhdlər", f"${float(t.get('cost_usd', 0.0)):.4f}"),
        ("uğursuz cəhdlər (ölçülən)", f"${wasted:.4f}"),
        (
            "ölçülməyən cəhdlər",
            f"{cov.get('unmeasured_attempts', 0)} / {cov.get('attempts', 0)} — "
            "xərci NAMƏLUM (sıfır deyil)",
        ),
    ]
    body = "".join(f"<tr><td>{esc(k)}</td><td class='num'>{esc(v)}</td></tr>" for k, v in rows)
    note = esc(str(cov.get("note", "")))
    return (
        "<h3>Xərc bölgüsü</h3><table><tbody>" + body + "</tbody></table>"
        + (f'<div class="note">{note}</div>' if note else "")
    )


def _section_cost_latency(record: RunRecord) -> str:
    res = record.results
    lat = [float(r.latency_ms) for r in res if r.latency_ms > 0]
    costs = [float(r.cost_usd) for r in res if r.cost_usd is not None]
    no_cost = [r for r in res if r.cost_usd is None]

    out = ['<h2 id="xerc">6 · Xərc və gecikmə paylanması</h2>']
    if not lat and not costs:
        out.append('<p class="sub">Nə gecikmə, nə xərc ölçülüb.</p>')
        return "".join(out)

    out.append('<div class="tiles">')
    for p in (50, 90, 95, 99):
        out.append(_tile(f"gecikmə p{p}", _fmt_ms(_percentile(lat, p))))
    out.append(_tile("gecikmə maks", _fmt_ms(max(lat) if lat else 0.0)))
    out.append(
        _tile(
            "xərc / case",
            f"${(sum(costs) / len(costs)) if costs else 0:.4f}",
            f"orta · maks ${max(costs) if costs else 0:.4f}",
        )
    )
    out.append("</div>")
    if no_cost:
        out.append(
            f'<div class="note">{len(no_cost)} case-də <code>usage</code> yoxdur — '
            "xərci hesablanmadı. Cəm xərc bu case-ləri SAYMIR (sıfır saymır, "
            "naməlum sayır).</div>"
        )
    out.append(_cost_split_note(record))
    out.append("<h3>Gecikmə paylanması (saniyə)</h3>")
    out.append(_histogram_svg([v / 1000 for v in lat], unit="s"))
    if costs:
        out.append("<h3>Xərc paylanması (USD / case)</h3>")
        out.append(_histogram_svg(costs, unit="$"))

    slow = sorted(res, key=lambda r: -r.latency_ms)[:10]
    rows = "".join(
        "<tr>"
        f'<td class="cid">{esc(r.case_id)}</td>'
        f'<td class="num">{_fmt_ms(float(r.latency_ms))}</td>'
        f'<td class="num">{"—" if r.cost_usd is None else f"${r.cost_usd:.4f}"}</td>'
        f'<td class="num">{r.attempt}</td>'
        f'<td>{esc(r.grade.grader)}</td>'
        f'<td class="{"pass" if r.grade.passed else ("skip" if r.grade.skipped else "fail")}">'
        f'{"keçdi" if r.grade.passed else ("skip" if r.grade.skipped else "sındı")}</td>'
        "</tr>"
        for r in slow
    )
    out.append(
        "<h3>Ən yavaş 10 case</h3><div class=\"scroll\"><table><thead><tr><th>case</th>"
        '<th class="num">gecikmə</th><th class="num">xərc</th><th class="num">cəhd</th>'
        "<th>grader</th><th>nəticə</th></tr></thead><tbody>"
        + rows
        + "</tbody></table></div>"
    )
    return "".join(out)


def _section_trend(record: RunRecord, history: Sequence[RunRecord]) -> str:
    out = ['<h2 id="trend">9 · Zamanla trend</h2>']
    known = {r.run_id: r for r in history}
    known[record.run_id] = record
    ordered = sorted(known.values(), key=lambda r: (r.started_at, r.run_id))

    same = [r for r in ordered if r.dataset_hash == record.dataset_hash]
    other = [r for r in ordered if r.dataset_hash != record.dataset_hash]

    if len(same) < 2:
        out.append(
            '<div class="warn">⚠️ TREND QURULMADI — eyni dataset üzərində cəmi '
            f"{len(same)} qaçış var (ən azı 2 lazımdır)."
            '<div class="body">Fərqli dataset-lərin keçmə dərəcələrini bir xətdə '
            "birləşdirmək düzgün deyil: rəqəmin dəyişməsi sistemin yox, sualların "
            "dəyişməsi ola bilər. Ona görə burada yalnız <code>dataset_hash</code> "
            f"= <code>{esc(record.dataset_hash or '?')}</code> olan qaçışlar sayılır."
            "</div></div>"
        )
    else:
        points = [
            (r.started_at[:16].replace("T", " "), float(r.totals.get("pass_rate", 0.0)))
            for r in same
        ]
        out.append(_trend_svg(points))

    rows = "".join(
        "<tr>"
        f'<td>{esc(r.started_at[:19].replace("T", " "))}</td>'
        f'<td class="cid">{esc(r.run_id)}</td>'
        f'<td>{esc(r.target)}@{esc(r.target_version or "?")}</td>'
        f'<td class="cid">{esc(r.dataset_hash or "?")}</td>'
        f'<td class="num">{int(r.totals.get("n_graded", 0))}</td>'
        f'<td class="num">{float(r.totals.get("pass_rate", 0.0)):.1%}</td>'
        f'<td class="num">${float(r.totals.get("cost_usd", 0.0)):.2f}</td>'
        f'<td class="num">{_fmt_ms(float(r.totals.get("p95_latency_ms", 0.0)))}</td>'
        f'<td>{"bu qaçış" if r.run_id == record.run_id else ("müqayisə olunur" if r.dataset_hash == record.dataset_hash else "fərqli dataset — müqayisə OLUNMUR")}</td>'
        "</tr>"
        for r in ordered
    )
    out.append(
        '<div class="scroll"><table><thead><tr><th>tarix</th><th>run_id</th><th>hədəf</th>'
        '<th>dataset</th><th class="num">case</th><th class="num">keçmə</th>'
        '<th class="num">xərc</th><th class="num">p95</th><th>qeyd</th>'
        "</tr></thead><tbody>" + rows + "</tbody></table></div>"
    )
    if other:
        out.append(
            f'<p class="sub">{len(other)} qaçış fərqli dataset üzərindədir və '
            "trend xəttinə daxil edilmir.</p>"
        )
    return "".join(out)


def _render_input(raw: Any, ctx: Ctx) -> str:
    if raw in (None, ""):
        return ctx.pick(
            '<p class="sub">Giriş mətni verilmədi — <code>--dataset</code> ilə '
            "dataset göstərilməyib və ya case dataset-də tapılmadı.</p>",
            '<p class="sub">Giriş mətni bu artefakta əlavə edilməyib: sorğunun tam '
            "mətni auditlə birlikdə təhvil verilən dataset faylındadır.</p>",
        )
    if isinstance(raw, str):
        text, clipped = _clip(raw)
        return f"<pre>{esc(text)}</pre>" + (
            '<p class="sub">… kəsildi</p>' if clipped else ""
        )
    parts = []
    for i, msg in enumerate(raw, start=1):
        role = msg.get("role", "?") if isinstance(msg, dict) else "?"
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        text, clipped = _clip(str(content))
        parts.append(
            f'<div class="turn"><div class="lbl">növbə {i} · {esc(role)}</div>'
            f"<pre>{esc(text)}</pre>"
            + ('<p class="sub">… kəsildi</p>' if clipped else "")
            + "</div>"
        )
    return "".join(parts)


def _case_block(
    result: CaseResult,
    case_input: Any,
    verdict: repro_mod.CaseVerdict | None,
    ctx: Ctx,
) -> str:
    grade = result.grade
    state = "skip" if grade.skipped else ("pass" if grade.passed else "fail")
    label = {"skip": "SKIP", "pass": "keçdi", "fail": "SINDI"}[state]
    pills = [f'<span class="pill sev-{esc(result.severity)}">{esc(result.severity)}</span>']
    if verdict is not None:
        pills.append(
            f'<span class="pill cls-{esc(verdict.classification)}">'
            f"{esc(verdict.classification)} {verdict.n_passed}/"
            f"{len(verdict.graded) or verdict.n_attempts}</span>"
        )
    # Taksonomiya kodu heç yerdə TƏK BAŞINA görünmür — kodun yanında insan
    # dilindəki adı olur; əks halda səhifə şifahi tərcümə tələb edir.
    pills += [f'<span class="pill">{esc(ctx.taxon(t))}</span>' for t in result.tags[:8]]

    haystack = " ".join(
        [result.case_id, grade.grader, grade.reason, result.severity, *result.tags]
    ).lower()

    resp = result.response
    body: list[str] = [
        f'<div class="field"><div class="lbl">grader səbəbi</div>'
        f'<div class="reason">{esc(grade.reason) or "—"}</div></div>',
        '<div class="field"><div class="lbl">giriş (tam)</div>'
        + _render_input(case_input, ctx)
        + "</div>",
    ]
    if resp.turns:
        turns = "".join(
            f'<div class="turn"><div class="lbl">növbə {i} cavabı '
            f"({_fmt_ms(float(t.latency_ms))})</div><pre>{esc(_clip(t.text)[0])}</pre></div>"
            for i, t in enumerate(resp.turns, start=1)
        )
        body.append(
            f'<div class="field"><div class="lbl">agent cavabı — növbə-növbə '
            f"({len(resp.turns)} növbə)</div>{turns}</div>"
        )
    text, clipped = _clip(resp.text)
    body.append(
        '<div class="field"><div class="lbl">agent cavabı (yekun, tam)</div>'
        f"<pre>{esc(text) or '(boş cavab)'}</pre>"
        + ('<p class="sub">… kəsildi</p>' if clipped else "")
        + "</div>"
    )
    if resp.error:
        body.append(
            '<div class="field"><div class="lbl">hədəf infrastruktur xətası</div>'
            f'<div class="reason">{esc(resp.error)}</div></div>'
        )
    if resp.tool_calls:
        calls = "\n".join(
            json.dumps(t.to_dict(), ensure_ascii=False, indent=2) for t in resp.tool_calls
        )
        body.append(
            f'<div class="field"><div class="lbl">tool çağırışları '
            f"({len(resp.tool_calls)})</div><pre>{esc(_clip(calls)[0])}</pre></div>"
        )
    if resp.retrieved:
        chunks = "\n\n".join(
            f"[{c.chunk_id}] score={c.score} doc={c.document}\n{_clip(c.text, 1200)[0]}"
            for c in resp.retrieved
        )
        body.append(
            f'<div class="field"><div class="lbl">retrieval ({len(resp.retrieved)} chunk)'
            f"</div><pre>{esc(_clip(chunks)[0])}</pre></div>"
        )
    if grade.evidence:
        body.append(
            '<div class="field"><div class="lbl">grader sübutu (evidence)</div>'
            f"<pre>{esc(_clip(json.dumps(grade.evidence, ensure_ascii=False, indent=2))[0])}"
            "</pre></div>"
        )
    if verdict is not None and verdict.attempts:
        rows = "".join(
            f'<tr><td class="num">{i}</td>'
            f'<td class="{"skip" if a.skipped else ("pass" if a.passed else "fail")}">'
            f'{"skip" if a.skipped else ("keçdi" if a.passed else "sındı")}</td>'
            f'<td class="reason">{esc(a.reason) or "—"}</td></tr>'
            for i, a in enumerate(verdict.attempts, start=1)
        )
        body.append(
            f'<div class="field"><div class="lbl">cəhd-cəhd nəticə '
            f'({verdict.classification})</div><div class="scroll"><table><thead><tr>'
            '<th class="num">cəhd</th><th>nəticə</th><th>səbəb</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div></div>"
        )
    meta = (
        f'<div class="field"><div class="lbl">ölçü</div><p class="sub">'
        f"gecikmə {_fmt_ms(float(result.latency_ms))} · xərc "
        f"{'—' if result.cost_usd is None else f'${result.cost_usd:.4f}'} · cəhd "
        f"{result.attempt} · usage "
        f"{esc(json.dumps(resp.usage.to_dict(), ensure_ascii=False) if resp.usage else 'yoxdur')}"
        "</p></div>"
    )
    body.append(meta)

    return (
        f'<details data-case="{esc(haystack)}"><summary>'
        f'<span class="cid">{esc(result.case_id)}</span>'
        f'<span class="{state}">{label}</span>'
        f'<span class="pill">{esc(grade.grader)}</span>'
        + "".join(pills)
        + f'<span class="sub reason-line">{esc(grade.reason[:110])}</span>'
        "</summary>"
        f'<div class="inner">{"".join(body)}</div></details>'
    )


def _section_failures(
    record: RunRecord,
    inputs: dict[str, Any],
    repro: repro_mod.ReproductionReport | None,
    ctx: Ctx,
) -> str:
    verdicts = {v.case_id: v for v in (repro.verdicts if repro else [])}
    failed = [r for r in record.results if not r.grade.passed and not r.grade.skipped]
    skipped = [r for r in record.results if r.grade.skipped]

    out = [
        f'<h2 id="sinan">10 · Sınan case-lər — tam giriş və çıxış ({len(failed)})</h2>',
        '<p class="sub">Hesabatın əsas dəyəri buradadır: hər sınmış case üçün '
        "göndərilən TAM giriş, agentin TAM cavabı, grader-in səbəbi və sübutu. "
        "Sətri açmadan da səbəb görünür.</p>",
    ]
    if not failed:
        out.append('<div class="ok">Bu qaçışda məzmun uğursuzluğu yoxdur.</div>')
    else:
        out.append(
            '<div class="filter"><input id="case-filter" type="search" '
            'placeholder="case id, grader, taq və ya səbəb üzrə süz…">'
            f'<div class="sub" id="case-filter-count">{len(failed)} case</div></div>'
        )
        order = {
            repro_mod.STABLE_FAIL: 0,
            repro_mod.UNSTABLE_FAIL: 1,
            repro_mod.FLAKY: 2,
        }
        sev = {"high": 0, "medium": 1, "low": 2}
        failed.sort(
            key=lambda r: (
                order.get(getattr(verdicts.get(r.case_id), "classification", ""), 3),
                sev.get(r.severity, 9),
                r.case_id,
            )
        )
        out += [
            _case_block(r, inputs.get(r.case_id), verdicts.get(r.case_id), ctx)
            for r in failed
        ]

    out.append(f'<h2 id="skip">11 · Qiymətləndirilməyən (skipped) case-lər ({len(skipped)})</h2>')
    if not skipped:
        out.append(
            '<div class="ok">Skipped case yoxdur — hər case üçün verdikt var.</div>'
        )
    else:
        out.append(
            '<p class="sub">Skip səssiz keçmə DEYİL: bu case-lər keçmə dərəcəsinin '
            "məxrəcinə daxil edilmir və ayrıca sayılır.</p>"
        )
        # Səbəb SİNFİ üzrə bölgü (AP-024): `rate_limit` gözləməklə keçir,
        # `credit_exhausted` keçmir — oxucu hansı olduğunu bilmədən qərar verə bilmir.
        by_reason = record.totals.get("skipped_by_reason") or {}
        if by_reason:
            out.append(
                '<div class="note">Səbəb sinifləri: '
                + " · ".join(
                    f"<b>{esc(k)}</b> {v} — {esc(REASON_HINT.get(k, ''))}"
                    for k, v in by_reason.items()
                )
                + "</div>"
            )
        rows = "".join(
            "<tr>"
            f'<td class="cid">{esc(r.case_id)}</td>'
            f"<td>{esc(r.grade.grader)}</td>"
            f'<td>{esc(reason_for_response(r.response) or "—")}</td>'
            f'<td><span class="pill sev-{esc(r.severity)}">{esc(r.severity)}</span></td>'
            f'<td class="reason">{esc(r.grade.reason) or "səbəb yazılmayıb"}</td></tr>'
            for r in skipped
        )
        out.append(
            '<div class="scroll"><table><thead><tr><th>case</th><th>grader</th>'
            "<th>səbəb sinfi</th><th>severity</th><th>səbəb</th></tr></thead><tbody>"
            + rows
            + "</tbody></table></div>"
        )
    return "".join(out)


def _section_method(record: RunRecord, dataset: str | None, ctx: Ctx) -> str:
    t = record.totals
    check = t.get("model_check") or {}
    # Müştəri versiyasında repo yolu deyil, faylın ADI verilir: dataset auditlə
    # birlikdə təhvil verilir, bizim qovluq strukturumuz isə verilmir.
    dataset_ref = (
        (Path(dataset).name if ctx.client else dataset) if dataset else ""
    )
    notes = [
        f"Dataset barmaq izi <code>{esc(record.dataset_hash or '?')}</code>"
        + (f" · fayl <code>{esc(dataset_ref)}</code>" if dataset_ref else ""),
        ctx.pick(
            f"Xərc <code>pricing/models.yaml</code> "
            f"({esc(t.get('price_table_as_of', '?'))}) "
            f"cədvəli ilə, qaçış tarixinə ({esc(t.get('priced_on', '?'))}) görə hesablanıb.",
            f"Xərc {esc(t.get('price_table_as_of', '?'))} tarixli qiymət cədvəli ilə, "
            f"qaçış tarixinə ({esc(t.get('priced_on', '?'))}) görə hesablanıb.",
        ),
        f"Hədəfin modeli: {model_line(record)}"
        + (f" — {esc(check.get('detail'))}" if check.get("detail") else ""),
        f"Tool izolyasiyası: {esc(t.get('lanes', '?'))} lane."
        + (
            ""
            if int(t.get("lanes", 0) or 0) > 0
            else " İzolyasiya konfiqurasiyası qeyd olunmayıb."
        ),
        "Keçmə dərəcəsinin məxrəci yalnız qiymətləndirilən case-lərdir; "
        "skipped case-lər nə keçmiş, nə sınmış sayılır.",
        "Bu səhifə tam oflayndır: heç bir CDN, şrift və ya piksel sorğusu yoxdur — "
        "müştəri datası kənara çıxmır.",
    ]
    return (
        '<h2 id="metod">12 · Metodologiya və provenans</h2><ul class="sub">'
        + "".join(f"<li>{n}</li>" for n in notes)
        + "</ul>"
    )


# --------------------------------------------- MƏCBURİ: ölçmənin öz auditi
def _judge_line(record: RunRecord) -> tuple[str, str]:
    """Judge qatının bir sətirlik halı — `(dəyər, sinif)`."""
    status = record.totals.get("judge")
    if not isinstance(status, dict):
        status = judge_status(r.grade.grader for r in record.results)
    if not status.get("used"):
        return ("işlədilməyib — bütün verdiktlər determinist grader-lərdən", "pass")
    if not status.get("calibrated"):
        return ("İŞLƏDİLİB, KALİBRASİYA YOXDUR — verdiktlər dərc oluna bilməz", "fail")
    return (
        f"uyğunluq {float(status.get('agreement', 0.0)):.1%} · "
        f"κ {float(status.get('kappa', 0.0)):.3f} · n={status.get('n', 0)} (§7)",
        "pass" if status.get("passed") else "fail",
    )


def _grader_mix(record: RunRecord) -> str:
    status = record.totals.get("judge")
    judge_graders = set(status.get("graders", []) if isinstance(status, dict) else [])
    graded = [r for r in record.results if not r.grade.skipped]
    n_judge = sum(1 for r in graded if r.grade.grader in judge_graders)
    n_det = len(graded) - n_judge
    return (
        f"{n_det} verdikt determinist grader-dən (oflayn yenidən hesablana bilər) · "
        f"{n_judge} verdikt model rəyindən"
    )


def _section_measurement_audit(
    record: RunRecord,
    delta: RunDelta | None,
    repro: repro_mod.ReproductionReport | None,
    ctx: Ctx,
) -> str:
    """MƏCBURİ bölmə — ölçmə alətinin ÖZ halı (CLIENT-REPORT.md §4).

    Şablonun əsaslandırması: auditin satdığı şey tapıntı siyahısı deyil,
    tapıntıların DOĞRU olmasıdır. Bölmə hesabatın öz zəifliyini göstərdiyi
    üçün kəsilmək istənir — ona görə burada maşınla saxlanılır: məlumat
    yoxdursa sətir yox olmur, «NAMƏLUM» yazılır.
    """
    t = record.totals
    out = [
        f'<h2 id="olcme-audit">4 · Ölçmənin öz auditi{MANDATORY_MARK}</h2>',
        '<div class="why"><b>Bu bölmə niyə var.</b> Yuxarıdakı rəqəmləri istehsal '
        "edən alətin özü də sınana bilər: yanlış assertion real uğursuzluğu "
        "«keçdi» kimi göstərə, düzgün cavabı isə «sındı» kimi saya bilər. Burada "
        "ölçmə qatının maşınla yoxlanan halı verilir. <b>Bura yazılmır:</b> hədəf "
        "sistemin qüsurları — onlar §10-dadır; ölçmə alətinin səhvini hədəfin "
        "səhvi kimi göstərmək uydurma tapıntıdır.</div>",
    ]

    if repro is None:
        gate = ("APARILMADI — sabit uğursuzluqla bir dəfəlik hadisə ayrılmayıb", "fail")
    elif not repro.classifiable:
        gate = (f"APARILMADI — {repro.notice}", "fail")
    else:
        c = repro.counts
        gate = (
            f"{repro.repeats} təkrar · dərc oluna bilən (stable-fail) "
            f"{c.get(repro_mod.STABLE_FAIL, 0)} · qapıdan keçməyən "
            f"{c.get(repro_mod.FLAKY, 0) + c.get(repro_mod.UNSTABLE_FAIL, 0)} "
            "(flaky + unstable-fail, §3-də sadalanır)",
            "pass",
        )

    cov = t.get("cost_coverage") or {}
    unmeasured = int(cov.get("unmeasured_attempts", 0) or 0)
    n_no_usage = sum(1 for r in record.results if r.cost_usd is None)
    rows: list[tuple[str, str, str]] = [
        ("Reproduksiya qapısı", gate[0], gate[1]),
        (
            "Baseline (reqressiya ölçüsü)",
            "var — §2-də müqayisə edilib" if delta is not None else "YOXDUR — reqressiya ölçülmədi",
            "pass" if delta is not None else "fail",
        ),
        ("Judge qatı", *_judge_line(record)),
        ("Verdiktlərin mənbəyi", _grader_mix(record), ""),
        (
            "Qiymətləndirilə bilməyən case (skipped)",
            f"{int(t.get('n_skipped', 0))} — bunlar ÖLÇMƏ uğursuzluğudur, "
            "hədəfin uğursuzluğu deyil (§11)",
            "skip" if int(t.get("n_skipped", 0)) else "pass",
        ),
        (
            "Xərc uçotunun tamlığı",
            (
                f"{unmeasured} cəhdin xərci ölçülmədi (naməlum, sıfır deyil)"
                if unmeasured
                else (
                    f"{n_no_usage} case-də usage yoxdur — xərci naməlumdur"
                    if n_no_usage
                    else "bütün ölçülən cəhdlərdə usage var"
                )
            ),
            "skip" if (unmeasured or n_no_usage) else "pass",
        ),
    ]
    body = "".join(
        f"<tr><td>{esc(k)}</td><td class=\"{cls}\">{esc(v)}</td></tr>" for k, v, cls in rows
    )
    out.append(
        '<div class="scroll"><table><thead><tr><th>ölçmə qatının yoxlaması</th>'
        f"<th>hal</th></tr></thead><tbody>{body}</tbody></table></div>"
    )

    # Əl ilə aparılan grader auditi (şablon §4-ün cədvəli) — varsa göstərilir,
    # yoxdursa bölmə SUSMUR: nəyin bilinmədiyi açıq yazılır.
    audit = t.get("grader_audit")
    if isinstance(audit, dict) and audit:
        order = [
            ("real", "REAL — agent həqiqətən səhv etdi"),
            ("measurement_gap", "ÖLÇMƏ BOŞLUĞU — cavab düzgün idi, assertion səhv idi"),
            ("ambiguous", "İKİMƏNALI — cavab qismən düzgün / sual natamam"),
        ]
        total = sum(int(audit.get(k, 0) or 0) for k, _ in order) or 1
        lines = "".join(
            f'<tr><td>{esc(label)}</td><td class="num">{int(audit.get(key, 0) or 0)}</td>'
            f'<td class="num">{int(audit.get(key, 0) or 0) / total:.0%}</td></tr>'
            for key, label in order
        )
        out.append(
            '<h3>Əl ilə oxunmuş uğursuzluqların təsnifatı</h3>'
            '<div class="scroll"><table><thead><tr><th>təsnifat</th>'
            '<th class="num">say</th><th class="num">pay</th></tr></thead>'
            f"<tbody>{lines}</tbody></table></div>"
        )
        false_green = int(audit.get("false_green", 0) or 0)
        out.append(
            f'<div class="note">Auditin üzə çıxardığı yalançı yaşıl: '
            f"<b>{false_green}</b> — ölçmənin «keçdi» saydığı, əslində REAL "
            "uğursuzluq olan case. Auditsiz bunlar görünməzdi."
            + (f" {esc(str(audit.get('note', '')))}" if audit.get("note") else "")
            + "</div>"
        )
    else:
        out.append(
            '<div class="warn">⚠️ ƏL İLƏ GRADER AUDİTİ BU ARTEFAKTDA QEYD OLUNMAYIB'
            '<div class="body">Yuxarıdakı sətirlər maşınla yoxlanan hissədir. '
            "Sınmış cavabların əl ilə oxunub «real uğursuzluq / ölçmə boşluğu / "
            "ikimənalı» kimi təsnif edilib-edilmədiyi bu qaçış qeydində yoxdur — "
            "yəni tapıntıların hansı hissəsinin grader artefaktı olduğu "
            "<b>NAMƏLUMDUR</b>. «Qeyd yoxdur» ilə «audit təmizdir» eyni şey deyil."
            "</div></div>"
        )
    return "".join(out)


# ------------------------------------------------ MƏCBURİ: nəyi ölçmədik
#: İstiqamət notasiyası — CLIENT-REPORT.md §8 ilə eyni.
UP = "↑ ŞİŞİRDİR"
DOWN = "↓ GİZLƏDİR"
BOTH = "↔ İKİ TƏRƏFLİ"


def _not_measured_items(
    record: RunRecord,
    delta: RunDelta | None,
    repro: repro_mod.ReproductionReport | None,
    history: Sequence[RunRecord],
) -> list[tuple[str, str, str, str]]:
    """`(nə ölçülmədi, niyə, istiqamət, nə çıxarıla bilməz)` — hamısı DATADAN."""
    t = record.totals
    items: list[tuple[str, str, str, str]] = []

    if delta is None:
        items.append((
            "Reqressiya",
            "Müqayisə üçün əvvəlki qaçışın snapshot-u verilməyib.",
            BOTH,
            "«Bu qaçışda vəziyyət pisləşdi / yaxşılaşdı»",
        ))
    if repro is None or not repro.classifiable or repro.repeats < 2:
        items.append((
            "Uğursuzluqların təkrarlanması",
            "Hər case bir dəfə ölçülüb; təkrarlanan uğursuzluqla bir dəfəlik "
            "hadisə ayrılmayıb.",
            BOTH,
            "«Bu uğursuzluq sabitdir» və ya «bu, bir dəfəlik hadisə idi»",
        ))
    else:
        c = repro.counts
        excluded = c.get(repro_mod.FLAKY, 0) + c.get(repro_mod.UNSTABLE_FAIL, 0)
        if excluded:
            items.append((
                f"Qapıdan keçməyən {excluded} case-in kök səbəbi",
                "Flaky və unstable-fail case-lər tapıntı kimi dərc olunmur; "
                "onların niyə qeyri-sabit olduğu bu auditdə araşdırılmayıb.",
                DOWN,
                "«Sadalanan tapıntılar sistemin BÜTÜN problemləridir»",
            ))

    cov = t.get("cost_coverage") or {}
    unmeasured = int(cov.get("unmeasured_attempts", 0) or 0)
    n_no_usage = sum(1 for r in record.results if r.cost_usd is None)
    if unmeasured or n_no_usage:
        items.append((
            "Xərcin tam uçotu",
            f"{unmeasured or n_no_usage} cəhdin token istifadəsi gəlmədi; "
            "onların xərci cəmə DAXİL DEYİL.",
            DOWN,
            "«Auditin/qaçışın xərci bu rəqəmdir» — rəqəm ALT HƏDDİR",
        ))

    n_skipped = int(t.get("n_skipped", 0))
    if n_skipped:
        items.append((
            f"{n_skipped} skipped case",
            "Bu case-lər qiymətləndirilə bilmədi və keçmə dərəcəsinin məxrəcinə "
            "daxil deyil.",
            BOTH,
            "«Keçmə dərəcəsi bütün case-ləri əhatə edir»",
        ))

    status = t.get("judge")
    if isinstance(status, dict) and status.get("used") and not status.get("calibrated"):
        items.append((
            "Judge-un insanla uyğunluğu",
            "LLM-judge işlədilib, amma kalibrasiya rəqəmi yoxdur.",
            BOTH,
            "«Judge verdiktləri insan qiymətləndirməsi ilə eynidir»",
        ))

    same = [r for r in history if r.dataset_hash == record.dataset_hash]
    if len(same) < 1:
        items.append((
            "Zamanla dəyişmə",
            "Eyni dataset üzərində yalnız bu qaçış var.",
            BOTH,
            "«Sistem yaxşılaşır / pisləşir»",
        ))

    untagged = sum(
        1 for r in record.results if not any(_TAXONOMY_TAG.match(x) for x in r.tags)
    )
    items.append((
        "Dataset-də olmayan uğursuzluq rejimləri",
        "Ölçü yalnız dataset-in əhatə etdiyi rejimləri görür"
        + (f"; {untagged} case-in rejim kodu yoxdur" if untagged else "")
        + ".",
        DOWN,
        "«Sistemdə başqa uğursuzluq rejimi yoxdur»",
    ))
    items.append((
        "Başqa model / konfiqurasiya",
        f"Ölçü bir hədəf üzərində aparılıb: {record.target}"
        f"@{record.target_version or '?'} · {record.model or '?'}.",
        BOTH,
        "«Nəticələr başqa model və ya konfiqurasiyaya köçürülür»",
    ))
    items.append((
        "İstehsalat trafikinin realizmi",
        "Case-lər hazırlanmış dataset-dəndir; real istifadəçi paylanması, "
        "yük və şəbəkə şəraiti ölçülməyib.",
        BOTH,
        "«Bu keçmə dərəcəsi istehsalatda görünəcək rəqəmdir»",
    ))
    items.append((
        "Gecikmə ölçüsünün mühiti",
        "p50/p95 audit mühitindən ölçülüb (şəbəkə, region, paralellik fərqlidir).",
        BOTH,
        "«İstifadəçinin görəcəyi gecikmə budur»",
    ))
    return items


def _section_not_measured(
    record: RunRecord,
    delta: RunDelta | None,
    repro: repro_mod.ReproductionReport | None,
    history: Sequence[RunRecord],
    ctx: Ctx,
) -> str:
    """MƏCBURİ bölmə — CLIENT-REPORT.md §8.

    Şablon bunu belə əsaslandırır: məhdudiyyəti gizlətmək auditdə ən tez
    tutulan şeydir, və müştəri bu hesabatla qərar verəcək — nəyin çıxarıla
    BİLMƏDİYİNİ bilməsə hesabat onu yanlış qərara aparır.
    """
    items = _not_measured_items(record, delta, repro, history)
    out = [
        f'<h2 id="olcmedik">8 · Nəyi ölçmədik{MANDATORY_MARK}</h2>',
        '<div class="why"><b>Bu bölmə niyə var.</b> Bu səhifədəki rəqəmlərin '
        "hüdudu var; hüdudu bilmədən oxunan rəqəm yanlış qərara aparır. Hər bənd "
        "dörd şeyi yazır — nə ölçülmədi · niyə · <b>istiqamət</b> (nəticəni hansı "
        "tərəfə əyir) · bundan nə çıxarıla BİLMƏZ. <b>Bura yazılmır:</b> üzrxahlıq. "
        "Aşağıdakılar qüsur deyil, ölçünün sərhədidir.</div>",
        '<div class="scroll"><table><thead><tr><th>işarə</th><th>mənası</th></tr>'
        "</thead><tbody>"
        f"<tr><td class=\"dir\">{UP}</td><td>uğursuzluqları real istehsalatdan ÇOX "
        "göstərir — rəqəm pessimistdir</td></tr>"
        f"<tr><td class=\"dir\">{DOWN}</td><td>uğursuzluqları AZ göstərir — rəqəm "
        "alt həddir</td></tr>"
        f"<tr><td class=\"dir\">{BOTH}</td><td>hər iki istiqamətdə səhv verə bilər; "
        "xalis təsir ölçülməyib</td></tr>"
        "</tbody></table></div>",
    ]
    rows = "".join(
        f"<tr><td><b>{esc(what)}</b></td><td>{esc(why)}</td>"
        f'<td class="dir">{esc(direction)}</td></tr>'
        for what, why, direction, _ in items
    )
    out.append(
        '<div class="scroll"><table><thead><tr><th>nə ölçülmədi</th><th>niyə</th>'
        f"<th>istiqamət</th></tr></thead><tbody>{rows}</tbody></table></div>"
    )
    cannot = "".join(
        f'<tr><td class="num">{i}</td><td>{esc(claim)}</td><td>{esc(what)}</td></tr>'
        for i, (what, _, _, claim) in enumerate(items, start=1)
    )
    out.append(
        "<h3>Bu hesabatdan çıxarıla BİLMƏYƏN nəticələr</h3>"
        '<div class="scroll"><table><thead><tr><th class="num">#</th>'
        "<th>çıxarıla BİLMƏYƏN nəticə</th><th>bloklayan məhdudiyyət</th>"
        f"</tr></thead><tbody>{cannot}</tbody></table></div>"
    )
    return "".join(out)


# ------------------------------------------------------------------- render
def _check_mandatory(page: str) -> None:
    """Məcburi bölmələr səhifədədirmi? Yoxsa hesabat dərc olunmur.

    Səssiz itmiş bölmə auditdə «problem yoxdur» kimi oxunur — ona görə bu
    yoxlama xəbərdarlıq deyil, istisnadır.
    """
    missing = [
        f"{sid} ({name})"
        for sid, name in MANDATORY_SECTIONS
        if f'id="{sid}"' not in page or name not in page
    ]
    if missing:
        raise MandatorySectionMissing(
            "Məcburi bölmə(lər) səhifədə yoxdur: "
            + ", ".join(missing)
            + " — bu bölmələr heç bir auditoriya üçün kəsilə bilməz "
            "(docs/templates/CLIENT-REPORT.md §4, §7, §8)."
        )


def render(
    record: RunRecord,
    delta: RunDelta | None = None,
    repro: repro_mod.ReproductionReport | None = None,
    history: Sequence[RunRecord] = (),
    case_inputs: dict[str, Any] | None = None,
    dataset_path: str | None = None,
    title: str = "",
    audience: str = INTERNAL,
    client_name: str = "",
    system_name: str = "",
    audit_date: str = "",
) -> str:
    """RunRecord (+ opsional delta/reproduksiya/tarixçə) → tam HTML səhifə.

    `audience="client"` yalnız DAXİLİ izləri çıxarır (tapşırıq nömrələri, repo
    yolları, daxili əmrlər). Ölçü nəticələri, məhdudiyyətlər və məcburi
    bölmələr hər iki rejimdə eynidir.
    """
    ctx = Ctx(
        audience=audience,
        client_name=client_name,
        system_name=system_name
        or (f"{record.target}@{record.target_version}" if record.target_version else record.target),
        audit_date=audit_date or (record.started_at[:10] if record.started_at else ""),
        labels=taxonomy_labels(),
    )
    inputs = dict(case_inputs or {})
    t = record.totals

    page_title = title or ctx.pick(
        DEFAULT_TITLE, f"{ctx.system_name} — etibarlılıq auditi"
    )
    subtitle = ctx.pick(
        f'{esc(record.target)}@{esc(record.target_version or "?")} · '
        f'{int(t.get("n_cases", len(record.results)))} case · '
        f'{esc(record.started_at[:19].replace("T", " "))}',
        f"Sifarişçi: {esc(ctx.client_name or 'göstərilməyib')} · "
        f"sınanan sistem: {esc(ctx.system_name)} · "
        f"audit tarixi: {esc(ctx.audit_date or '?')} · "
        f'{int(t.get("n_cases", len(record.results)))} case · '
        f"qaçış <code>{esc(record.run_id)}</code>",
    )

    nav = [
        ("#xulase", "Xülasə"),
        ("#baseline", "Baseline"),
        ("#repro", "Reproduksiya"),
        ("#olcme-audit", "Ölçmənin auditi"),
        ("#kateqoriya", "Kateqoriya"),
        ("#xerc", "Xərc/gecikmə"),
        ("#judge", "Judge"),
        ("#olcmedik", "Nəyi ölçmədik"),
        ("#trend", "Trend"),
        ("#sinan", "Sınan case-lər"),
        ("#skip", "Skipped"),
        ("#metod", "Metod"),
    ]
    parts = [
        "<!doctype html>",
        '<html lang="az"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{esc(page_title)} — "
        f"{esc(ctx.pick(record.target, ctx.system_name))} {esc(record.run_id)}</title>",
        f"<style>{CSS}</style></head><body><div class=\"wrap\">",
        "<nav>" + "".join(f'<a href="{h}">{esc(n)}</a>' for h, n in nav) + "</nav>",
        f"<h1>{esc(page_title)}</h1>",
        f'<p class="sub">{subtitle}</p>',
        _section_meta(record, repro, ctx),
        '<h2 id="xulase">1 · Xülasə</h2>',
        _section_summary(record, repro),
        _section_baseline(record, delta, ctx),
        _section_reproduction(repro, ctx),
        _section_measurement_audit(record, delta, repro, ctx),
        _section_categories(record, ctx),
        _section_cost_latency(record),
        _section_judge(record, ctx),
        _section_not_measured(record, delta, repro, history, ctx),
        _section_trend(record, history),
        _section_failures(record, inputs, repro, ctx),
        _section_method(record, dataset_path, ctx),
        "<footer>AgentProof · statik hesabat, xarici asılılıq yoxdur · "
        f'qaçış <code>{esc(record.run_id)}</code></footer>',
        "</div>",
        f"<script>{JS}</script>",
        "</body></html>",
    ]
    page = "".join(parts)
    if ctx.client:
        # Mənbədə auditoriyaya görə yazılır; bu, ikinci qatdır — gözdən qaçan
        # daxili iz səssiz qalmasın deyə GÖRÜNƏN nişanla əvəz olunur.
        page = scrub_internal(page)
    _check_mandatory(page)
    return page


# ---------------------------------------------------------------------- CLI
def _autodiscover(run_dir: Path) -> tuple[Path | None, Path | None]:
    """Qaçış qovluğundan RunRecord və reproduksiya JSON-unu tapır."""
    records = sorted(p for p in run_dir.glob("*.json") if p.name != "reproduction.json")
    repro = run_dir / "reproduction.json"
    return (records[0] if records else None), (repro if repro.exists() else None)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="agentproof-html", description="Statik HTML audit hesabatı"
    )
    p.add_argument("run", help="qaçış qovluğu və ya RunRecord JSON faylı")
    p.add_argument("--out", default=None, help="çıxış faylı (default: <qovluq>/index.html)")
    p.add_argument("--baseline", default=None, help="baseline RunRecord JSON")
    p.add_argument("--repro", default=None, help="reproduction.json (default: qovluqdan)")
    p.add_argument("--dataset", default=None,
                   help="sınmış case-lərin TAM girişi üçün dataset jsonl")
    p.add_argument("--history", nargs="*", default=[],
                   help="trend üçün əvvəlki qaçışlar (qovluq və ya JSON)")
    p.add_argument("--title", default="",
                   help="başlıq (default: auditoriyaya görə seçilir)")
    p.add_argument("--audience", choices=list(AUDIENCES), default=INTERNAL,
                   help="client: daxili izlər (tapşırıq nömrəsi, repo yolu, "
                        "daxili əmr) çıxarılır — ölçü nəticələri dəyişmir")
    p.add_argument("--client", default="", help="sifarişçinin adı (başlıq üçün)")
    p.add_argument("--system", default="", help="sınanan sistemin adı (başlıq üçün)")
    p.add_argument("--audit-date", default="", help="audit tarixi (başlıq üçün)")
    args = p.parse_args(argv)

    run_path = Path(args.run)
    if run_path.is_dir():
        record_path, repro_path = _autodiscover(run_path)
        if record_path is None:
            print(f"RunRecord tapılmadı: {run_path}", file=sys.stderr)
            return 2
        out = Path(args.out) if args.out else run_path / "index.html"
    else:
        record_path, repro_path = run_path, None
        out = Path(args.out) if args.out else run_path.with_name("index.html")
    if args.repro:
        repro_path = Path(args.repro)

    record = RunRecord.from_dict(json.loads(record_path.read_text(encoding="utf-8")))

    repro = None
    if repro_path and repro_path.exists():
        repro = repro_mod.report_from_dict(json.loads(repro_path.read_text(encoding="utf-8")))

    delta = None
    if args.baseline:
        base_path = Path(args.baseline)
        if base_path.exists():
            from agentproof.report.baseline import compare  # lokal: yüngül import

            baseline = RunRecord.from_dict(json.loads(base_path.read_text(encoding="utf-8")))
            delta = compare(record, baseline)
        else:
            print(f"Baseline tapılmadı: {base_path} — bölmə xəbərdarlıq göstərəcək.",
                  file=sys.stderr)

    inputs: dict[str, Any] = {}
    if args.dataset:
        inputs = load_case_inputs(args.dataset)

    html = render(
        record,
        delta=delta,
        repro=repro,
        history=load_records(args.history),
        case_inputs=inputs,
        dataset_path=args.dataset,
        title=args.title,
        audience=args.audience,
        client_name=args.client,
        system_name=args.system,
        audit_date=args.audit_date,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"HTML hesabat: {out}  ({len(html) / 1024:.0f} KB) · auditoriya: {args.audience}")
    if args.audience == CLIENT:
        redacted = html.count(REDACTED)
        if redacted:  # mənbə təmizliyi buraxıbsa redaktor tutub — amma susmuruq
            print(
                f"  DİQQƏT: {redacted} daxili iz redaktə nişanı ilə əvəz olundu — "
                "mənbə mətni düzəldilməlidir.",
                file=sys.stderr,
            )
        verbatim = "".join(c for is_verbatim, c in _split_verbatim(html) if is_verbatim)
        seen = sorted({m for _, rx in INTERNAL_TRACE_PATTERNS for m in rx.findall(verbatim)})
        if seen:
            print(
                f"  qeyd: sübut mətnində daxili görünüşlü {len(seen)} ifadə var — "
                "sübut REDAKTƏ OLUNMUR, əl ilə baxın: " + ", ".join(seen[:5]),
                file=sys.stderr,
            )
    if repro is None:
        print("  qeyd: reproduksiya JSON verilmədi — hesabatda xəbərdarlıq görünür.",
              file=sys.stderr)
    if delta is None:
        print("  qeyd: baseline verilmədi — REQRESSİYA YOXLANILMADI.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Statik HTML audit hesabatı (STACK.md §8.5, AP-012).

    render(record, delta=None, repro=None, ...) -> str        # HTML mətni
    python -m agentproof.report.html reports/full-run-02      # -> index.html

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

Bu modul `inspect_ai` import ETMİR: hesabat qaçış mühərriki qurulmamış maşında
da render olunmalıdır (`report/normalize.py` Inspect-i bilən yeganə fayldır).
"""

from __future__ import annotations

import argparse
import html as _html
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

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
def _section_meta(record: RunRecord, repro: repro_mod.ReproductionReport | None) -> str:
    t = record.totals
    check = t.get("model_check") or {}
    rows = [
        ("qaçış (run_id)", record.run_id),
        ("hədəf", f"{record.target}@{record.target_version or '?'}"),
        ("hədəfin modeli", model_line(record)),
        ("başlama", record.started_at),
        ("dataset hash", record.dataset_hash or "?"),
        ("case sayı", str(t.get("n_cases", len(record.results)))),
        ("təkrar (--repeat)", str(repro.repeats) if repro else "bilinmir"),
        ("izolyasiya lane", str(t.get("lanes", "?"))),
        ("çoxnövbəli case", str(t.get("multi_turn_cases", 0))),
        ("qiymət cədvəli", f"{t.get('price_table_as_of', '?')} · dərəcə {t.get('priced_on', '?')}"),
        ("model yoxlaması", check.get("status", "yoxlanılmayıb")),
        ("hesabat", datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")),
    ]
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
        _tile("xərc", f"${float(t.get('cost_usd', 0.0)):.2f}", "bütün case, bütün təkrar"),
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


def _section_baseline(record: RunRecord, delta: RunDelta | None) -> str:
    out = ['<h2 id="baseline">2 · Baseline müqayisəsi</h2>']
    if delta is None:
        out.append(
            f'<div class="warn">⚠️ {esc(BASELINE_MISSING)}'
            '<div class="body">Qoşmaq üçün: <code>python evals/run.py … '
            "--baseline evals/baselines/&lt;hədəf&gt;@&lt;versiya&gt;.json "
            "--fail-on-regression</code></div></div>"
        )
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


def _section_reproduction(repro: repro_mod.ReproductionReport | None) -> str:
    out = ['<h2 id="repro">3 · Reproduksiya təsnifatı</h2>']
    if repro is None:
        out.append(
            '<div class="warn">⚠️ REPRODUKSİYA TƏSNİFATI YOXDUR — hər case yalnız '
            "BİR dəfə ölçülüb sayılmalıdır."
            '<div class="body">Bu səhifədəki heç bir uğursuzluq «sabit» deyil: '
            "təkrarlanan uğursuzluqla bir dəfəlik hadisə ayrılmayıb. Qoşmaq üçün: "
            "<code>python evals/reproduce.py &lt;qaçış qovluğu&gt;</code> "
            "(və ya <code>--repro</code> ilə hazır JSON ver).</div></div>"
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


def _section_judge(record: RunRecord) -> str:
    """MƏCBURİ bölmə — judge işlədilməyibsə də görünür (DoD, JUDGE-CALIBRATION §6)."""
    status = record.totals.get("judge")
    if not isinstance(status, dict):
        status = judge_status(r.grade.grader for r in record.results)

    out = ['<h2 id="judge">4 · Judge kalibrasiyası</h2>']
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
        out.append(
            f'<div class="warn">⚠️ KALİBRASİYA EDİLMƏMİŞ JUDGE — NƏTİCƏ MÜDAFİƏ '
            f'OLUNMUR<div class="body">{esc(status.get("warning", ""))}<br>'
            f"Judge grader-ləri: {graders}<br>"
            "Düzəliş: <code>python evals/calibration/run_calibration.py</code>"
            "</div></div>"
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


def _section_categories(record: RunRecord, labels: dict[str, str]) -> str:
    res = record.results
    return (
        '<h2 id="kateqoriya">5 · Kateqoriya üzrə keçmə dərəcəsi</h2>'
        '<p class="sub">Bir case bir neçə taqda görünə bilər — sətir cəmləri '
        "case sayından böyük ola bilər. «keçmə» məxrəci yalnız qiymətləndirilən "
        "(skip olmayan) case-lərdir.</p>"
        "<h3>Uğursuzluq rejimi (FAILURE-TAXONOMY kodu)</h3>"
        + _bucket_table(by_taxonomy(res, labels), "kod")
        + "<h3>Grader</h3>"
        + _bucket_table(by_grader(res), "grader")
        + "<h3>Severity</h3>"
        + _bucket_table(by_severity(res), "severity")
        + "<h3>Mövzu taqları (ən çox sınan 25)</h3>"
        + _bucket_table(by_tag(res), "taq")
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
    out = ['<h2 id="trend">7 · Zamanla trend</h2>']
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


def _render_input(raw: Any) -> str:
    if raw in (None, ""):
        return (
            '<p class="sub">Giriş mətni verilmədi — <code>--dataset</code> ilə '
            "dataset göstərilməyib və ya case dataset-də tapılmadı.</p>"
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
    pills += [f'<span class="pill">{esc(t)}</span>' for t in result.tags[:8]]

    haystack = " ".join(
        [result.case_id, grade.grader, grade.reason, result.severity, *result.tags]
    ).lower()

    resp = result.response
    body: list[str] = [
        f'<div class="field"><div class="lbl">grader səbəbi</div>'
        f'<div class="reason">{esc(grade.reason) or "—"}</div></div>',
        '<div class="field"><div class="lbl">giriş (tam)</div>'
        + _render_input(case_input)
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
        + f'<span class="sub">{esc(grade.reason[:110])}</span>'
        "</summary>"
        f'<div class="inner">{"".join(body)}</div></details>'
    )


def _section_failures(
    record: RunRecord,
    inputs: dict[str, Any],
    repro: repro_mod.ReproductionReport | None,
) -> str:
    verdicts = {v.case_id: v for v in (repro.verdicts if repro else [])}
    failed = [r for r in record.results if not r.grade.passed and not r.grade.skipped]
    skipped = [r for r in record.results if r.grade.skipped]

    out = [
        f'<h2 id="sinan">8 · Sınan case-lər — tam giriş və çıxış ({len(failed)})</h2>',
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
        out += [_case_block(r, inputs.get(r.case_id), verdicts.get(r.case_id)) for r in failed]

    out.append(f'<h2 id="skip">9 · Qiymətləndirilməyən (skipped) case-lər ({len(skipped)})</h2>')
    if not skipped:
        out.append(
            '<div class="ok">Skipped case yoxdur — hər case üçün verdikt var.</div>'
        )
    else:
        out.append(
            '<p class="sub">Skip səssiz keçmə DEYİL: bu case-lər keçmə dərəcəsinin '
            "məxrəcinə daxil edilmir və ayrıca sayılır.</p>"
        )
        rows = "".join(
            "<tr>"
            f'<td class="cid">{esc(r.case_id)}</td>'
            f"<td>{esc(r.grade.grader)}</td>"
            f'<td><span class="pill sev-{esc(r.severity)}">{esc(r.severity)}</span></td>'
            f'<td class="reason">{esc(r.grade.reason) or "səbəb yazılmayıb"}</td></tr>'
            for r in skipped
        )
        out.append(
            '<div class="scroll"><table><thead><tr><th>case</th><th>grader</th>'
            "<th>severity</th><th>səbəb</th></tr></thead><tbody>"
            + rows
            + "</tbody></table></div>"
        )
    return "".join(out)


def _section_method(record: RunRecord, dataset: str | None) -> str:
    t = record.totals
    check = t.get("model_check") or {}
    notes = [
        f"Dataset barmaq izi <code>{esc(record.dataset_hash or '?')}</code>"
        + (f" · fayl <code>{esc(dataset)}</code>" if dataset else ""),
        f"Xərc <code>pricing/models.yaml</code> ({esc(t.get('price_table_as_of', '?'))}) "
        f"cədvəli ilə, qaçış tarixinə ({esc(t.get('priced_on', '?'))}) görə hesablanıb.",
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
        '<h2 id="metod">10 · Metodologiya və provenans</h2><ul class="sub">'
        + "".join(f"<li>{n}</li>" for n in notes)
        + "</ul>"
    )


# ------------------------------------------------------------------- render
def render(
    record: RunRecord,
    delta: RunDelta | None = None,
    repro: repro_mod.ReproductionReport | None = None,
    history: Sequence[RunRecord] = (),
    case_inputs: dict[str, Any] | None = None,
    dataset_path: str | None = None,
    title: str = "AgentProof audit hesabatı",
) -> str:
    """RunRecord (+ opsional delta/reproduksiya/tarixçə) → tam HTML səhifə."""
    inputs = dict(case_inputs or {})
    labels = taxonomy_labels()
    t = record.totals

    nav = [
        ("#xulase", "Xülasə"),
        ("#baseline", "Baseline"),
        ("#repro", "Reproduksiya"),
        ("#judge", "Judge"),
        ("#kateqoriya", "Kateqoriya"),
        ("#xerc", "Xərc/gecikmə"),
        ("#trend", "Trend"),
        ("#sinan", "Sınan case-lər"),
        ("#skip", "Skipped"),
        ("#metod", "Metod"),
    ]
    parts = [
        "<!doctype html>",
        '<html lang="az"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{esc(title)} — {esc(record.target)} {esc(record.run_id)}</title>",
        f"<style>{CSS}</style></head><body><div class=\"wrap\">",
        "<nav>" + "".join(f'<a href="{h}">{esc(n)}</a>' for h, n in nav) + "</nav>",
        f"<h1>{esc(title)}</h1>",
        f'<p class="sub">{esc(record.target)}@{esc(record.target_version or "?")} · '
        f'{int(t.get("n_cases", len(record.results)))} case · '
        f'{esc(record.started_at[:19].replace("T", " "))}</p>',
        _section_meta(record, repro),
        '<h2 id="xulase">1 · Xülasə</h2>',
        _section_summary(record, repro),
        _section_baseline(record, delta),
        _section_reproduction(repro),
        _section_judge(record),
        _section_categories(record, labels),
        _section_cost_latency(record),
        _section_trend(record, history),
        _section_failures(record, inputs, repro),
        _section_method(record, dataset_path),
        "<footer>AgentProof · statik hesabat, xarici asılılıq yoxdur · "
        f'qaçış <code>{esc(record.run_id)}</code></footer>',
        "</div>",
        f"<script>{JS}</script>",
        "</body></html>",
    ]
    return "".join(parts)


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
    p.add_argument("--title", default="AgentProof audit hesabatı")
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
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"HTML hesabat: {out}  ({len(html) / 1024:.0f} KB)")
    if repro is None:
        print("  qeyd: reproduksiya JSON verilmədi — hesabatda xəbərdarlıq görünür.",
              file=sys.stderr)
    if delta is None:
        print("  qeyd: baseline verilmədi — REQRESSİYA YOXLANILMADI.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

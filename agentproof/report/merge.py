"""Qaçış birləşməsi — əvəz olunan (superseded) nəticələr (AP-042).

PROBLEM
-------
`full-run-03`-də 25 case `skipped` bitdi (Anthropic kreditləri tükəndi).
Kredit bərpa olunandan sonra həmin 25 case `full-run-03b`-də uğurla qaçdı.
İki qaçış birlikdə oxunanda alət 187 case gördü: 162 + 25. Halbuki dataset-də
o qədər case yoxdur — 25-i İKİ DƏFƏ sayılmışdı və hesabatda "25 case
ölçülmədi" yazısı qalmışdı, halbuki hamısı ölçülmüşdü.

QAYDA
-----
Eyni `case_id` bir neçə qaçışda varsa, ƏN SON qaçışın nəticəsi götürülür.
"Ən son" YALNIZ `started_at` (RunRecord) / `created` (`.eval` log) tarixinə
görə müəyyən edilir — fayl adına, arqument sırasına və ya nəticənin
"yaxşılığına" görə YOX. Seçim qaydası zaman olmalıdır, nəticə yox: əks halda
alət "uğurlu nəticəni üstün tut" deyərək sonrakı REQRESSİYANI gizlədərdi.

Əvəz olunan nəticə SİLİNMİR. `superseded` siyahısına düşür, sayı hesabatda
görünür və hansı qaçışın onu əvəz etdiyi yazılır. Auditor artefaktı susdurmur:
"bu case iki dəfə ölçüldü, ikincisini götürdük" ilə "bu case bir dəfə ölçüldü"
fərqli iddialardır.

DATASET SƏRHƏDİ
---------------
Əvəzləmə YALNIZ eyni `dataset_hash` daxilində baş verir. Fərqli dataset-lərdən
gələn eyni `case_id` ayrı-ayrı qalır — case-in mətni dəyişibsə, iki nəticəni
birləşdirmək səssiz korlanmadır.

Praktikada bu sərhəd HƏDDİNDƏN ARTIQ dar çıxa bilər: `runner/task.py`-də
`dataset_hash(cases)` FİLTRDƏN SONRAKI case-lərə görə hesablanır, yəni o,
dataset-in versiyasını yox, SEÇİLMİŞ ALT DƏSTİ imzalayır. `--filter` ilə
qaçırılan təkrar qaçışın hash-i ana qaçışdan həmişə fərqlənir. Ona görə
`allow_cross_dataset` açıq açarı var: verilibsə əvəzləmə hash sərhədini keçir,
AMMA yalnız case tərifinin barmaq izi (`fingerprint`) hər iki qaçışda eyni
olduqda. Barmaq izləri fərqlidirsə həmin case HEÇ VAXT birləşdirilmir.
Barmaq izi ümumiyyətlə yoxdursa (RunRecord-da case mətni saxlanmır) birləşmə
baş verir, amma xəbərdarlıq hesabata yazılır.

Bu modul `inspect_ai` import ETMİR (STACK.md §6).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from agentproof.report.cost import COMPLETE, PARTIAL, UNMEASURED
from agentproof.types import SCHEMA_VERSION, CaseResult, RunRecord

#: `evals/datasets/COVERAGE.md` §4: `baseline` teqli case-lər sistemin HAZIRDA
#: keçməsi gözlənilən hallardır — reqressiya məhz orada ölçülür. Ona görə
#: birləşmiş qeyddə onların vəziyyəti AYRICA görünür: ümumi keçmə dərəcəsi
#: sabit qalıb bu dəstdə 3 case sınsa, bu, ümumi rəqəmdə itərdi.
BASELINE_TAG = "baseline"


# ------------------------------------------------------------------ mənşə
@dataclass(frozen=True)
class RunOrigin:
    """Bir nəticənin HANSI qaçışdan gəldiyi.

    `source` yalnız insan üçün etiketdir (fayl yolu). Sıralamada İŞLƏNMİR —
    fayl adına görə "sonuncunu" seçmək məhz AP-042-nin qadağan etdiyi şeydir.
    """

    run_id: str = ""
    started_at: str = ""
    dataset_hash: str = ""
    source: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        """Qaçışı eyniləşdirən açar (etiketsiz)."""
        return (self.run_id, self.started_at, self.dataset_hash)

    @property
    def moment(self) -> datetime | None:
        """`started_at` -> UTC datetime. Oxunmursa `None` (sıralama mümkün deyil)."""
        return parse_moment(self.started_at)

    @property
    def label(self) -> str:
        bits = [self.run_id or "?", self.started_at or "tarixsiz"]
        if self.source:
            bits.append(self.source)
        return " · ".join(bits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "dataset_hash": self.dataset_hash,
            "source": self.source,
        }


def parse_moment(value: str) -> datetime | None:
    """ISO tarix -> UTC datetime; oxunmursa `None`.

    `None` "çox köhnə" demək DEYİL: tarixi oxunmayan qaçış SIRALANA BİLMİR,
    ona görə əvəzləmədə iştirak etmir (aşağıda açıq xəbərdarlıqla).
    """
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    # Zolaqsız tarix UTC sayılır — əks halda zolaqlı ilə müqayisə TypeError verir.
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp


# ---------------------------------------------------------------- nəticələr
@dataclass(frozen=True)
class SupersededEntry:
    """Əvəz olunmuş (amma SİLİNMƏMİŞ) nəticə."""

    case_id: str
    origin: RunOrigin
    superseded_by: RunOrigin
    n_items: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "origin": self.origin.to_dict(),
            "superseded_by": self.superseded_by.to_dict(),
            "n_items": self.n_items,
        }


@dataclass
class MergedCase:
    """Birləşmədən sonra bir case üçün SAXLANAN nəticələr."""

    case_id: str
    origins: list[RunOrigin] = field(default_factory=list)
    items: list[Any] = field(default_factory=list)
    dataset_hash: str = ""
    cross_dataset: bool = False
    """Bu case başqa `dataset_hash` altında da var — birləşdirilmədi, ayrı qaldı."""

    @property
    def origin(self) -> RunOrigin:
        return self.origins[-1] if self.origins else RunOrigin()


@dataclass
class MergeOutcome:
    cases: list[MergedCase] = field(default_factory=list)
    superseded: list[SupersededEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def n_superseded(self) -> int:
        return sum(e.n_items for e in self.superseded)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_cases": len(self.cases),
            "n_superseded": self.n_superseded,
            "superseded": [e.to_dict() for e in self.superseded],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class MergeItem:
    """Birləşməyə girən bir vahid."""

    case_id: str
    origin: RunOrigin
    payload: Any
    fingerprint: str = ""
    """Case TƏRİFİNİN barmaq izi (varsa) — hash sərhədini keçməyin yeganə sübutu."""


def fingerprint_case(meta: Any) -> str:
    """Case tərifinin sabit barmaq izi (`.eval` log metadata-sı üçün)."""
    import json

    try:
        payload = json.dumps(meta, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ birləşmə
@dataclass
class _Events:
    """Case-lər üzrə yığılan hadisələr — xəbərdarlıq SONDA yekunlaşdırılır.

    Case başına ayrıca xəbərdarlıq yazsaq, 25 case-lik birləşmə 25 eyni sətir
    verərdi və oxucu onları keçərdi. Yekun sətir sayı GÖSTƏRİR, nümunə verir.
    """

    cross_blocked: dict[str, list[str]] = field(default_factory=dict)
    cross_merged: list[str] = field(default_factory=list)
    cross_unverified: list[str] = field(default_factory=list)
    cross_mismatch: list[str] = field(default_factory=list)
    undated: list[str] = field(default_factory=list)


def merge_items(
    items: Sequence[MergeItem],
    *,
    supersede: bool = True,
    allow_cross_dataset: bool = False,
) -> MergeOutcome:
    """Case üzrə birləşdir: eyni case_id-nin ƏN SON qaçışını saxla.

    `supersede=False` — heç nə əvəz olunmur: hər qaçış müstəqil CƏHD kimi
    qalır. `evals/reproduce.py`-in sənədləşmiş "bir neçə müstəqil qaçışın
    RunRecord-u" rejimi budur.
    """
    outcome = MergeOutcome()
    events = _Events()
    order: list[str] = []
    by_case: dict[str, dict[tuple[str, str, str], list[MergeItem]]] = {}
    for item in items:
        if item.case_id not in by_case:
            by_case[item.case_id] = {}
            order.append(item.case_id)
        by_case[item.case_id].setdefault(item.origin.key, []).append(item)

    for case_id in order:
        slices = list(by_case[case_id].values())
        pools = _split_pools(case_id, slices, allow_cross_dataset, events)
        for pool in pools:
            outcome.cases.append(
                _resolve_pool(case_id, pool, supersede, len(pools) > 1, outcome, events)
            )
    outcome.warnings += _summarize(events, allow_cross_dataset)
    return outcome


def _sample(ids: Sequence[str], limit: int = 5) -> str:
    head = ", ".join(ids[:limit])
    return head + (f" … (+{len(ids) - limit})" if len(ids) > limit else "")


def _summarize(events: _Events, allow_cross_dataset: bool) -> list[str]:
    out: list[str] = []
    if events.cross_blocked:
        listed = ", ".join(sorted({h for hs in events.cross_blocked.values() for h in hs}))
        ids = sorted(events.cross_blocked)
        out.append(
            f"{len(ids)} case FƏRQLİ dataset_hash-larda göründü ({listed}) və "
            f"BİRLƏŞDİRİLMƏDİ — ayrı-ayrı sayılır: {_sample(ids)}. "
            "Eyni id başqa dataset-də başqa case ola bilər; susmaqla birləşdirmək "
            "səssiz korlanma olardı. Dataset-lərin uyğunluğuna əminsənsə: "
            "--merge-across-datasets"
        )
    if events.cross_mismatch:
        out.append(
            f"{len(events.cross_mismatch)} case --merge-across-datasets ilə də "
            "birləşdirilmədi: case TƏRİFİ qaçışlar arasında fərqlidir "
            f"(eyni id, fərqli sual): {_sample(sorted(events.cross_mismatch))}"
        )
    if events.cross_merged:
        out.append(
            f"{len(events.cross_merged)} case fərqli dataset_hash-lardan birləşdirildi "
            "(--merge-across-datasets); case TƏRİFİNİN barmaq izi hər iki qaçışda "
            f"EYNİDİR, yəni birləşmə yoxlanılıb: {_sample(sorted(events.cross_merged))}"
        )
    if events.cross_unverified:
        out.append(
            f"{len(events.cross_unverified)} case fərqli dataset_hash-lardan birləşdirildi "
            "(--merge-across-datasets), amma case tərifi artefaktda SAXLANMIR — barmaq "
            f"izi ilə YOXLANMADI, doğruluğu operator təsdiqləyib: "
            f"{_sample(sorted(events.cross_unverified))}"
        )
    if events.undated:
        out.append(
            f"{len(events.undated)} case-də qaçışların bir hissəsində oxunan tarix yoxdur — "
            "'ən son' müəyyən edilə bilmir, əvəzləmə APARILMADI, nəticələr cəhd sayılır: "
            f"{_sample(sorted(events.undated))}"
        )
    return out


def _hash_of(group: Sequence[MergeItem]) -> str:
    return group[0].origin.dataset_hash


def _by_hash(slices: list[list[MergeItem]]) -> list[list[list[MergeItem]]]:
    pools: dict[str, list[list[MergeItem]]] = {}
    for s in slices:
        pools.setdefault(_hash_of(s), []).append(s)
    return [pools[h] for h in sorted(pools)]


def _split_pools(
    case_id: str,
    slices: list[list[MergeItem]],
    allow_cross_dataset: bool,
    events: _Events,
) -> list[list[list[MergeItem]]]:
    """Qaçış dilimlərini `dataset_hash` üzrə hovuzlara böl.

    Bir hovuz = daxilində əvəzləmə İCAZƏLİ olan dilimlər.
    """
    hashes = {_hash_of(s) for s in slices}
    if len(hashes) < 2:
        return [slices]

    if not allow_cross_dataset:
        events.cross_blocked[case_id] = sorted(h or "?" for h in hashes)
        return _by_hash(slices)

    prints = {i.fingerprint for s in slices for i in s if i.fingerprint}
    if len(prints) > 1:
        events.cross_mismatch.append(case_id)
        return _by_hash(slices)

    (events.cross_merged if prints else events.cross_unverified).append(case_id)
    return [slices]


def _resolve_pool(
    case_id: str,
    pool: list[list[MergeItem]],
    supersede: bool,
    cross_dataset: bool,
    outcome: MergeOutcome,
    events: _Events,
) -> MergedCase:
    """Bir hovuzda qalibi seç, qalanını `superseded` kimi qeyd et."""
    origins = [group[0].origin for group in pool]
    if not supersede or len(pool) < 2:
        return _collect(case_id, pool, cross_dataset)

    moments = [o.moment for o in origins]
    if any(m is None for m in moments):
        events.undated.append(case_id)
        return _collect(case_id, pool, cross_dataset)

    latest = max(moments)  # type: ignore[type-var]
    winners = [g for g, m in zip(pool, moments) if m == latest]
    losers = [(g, o) for g, o, m in zip(pool, origins, moments) if m != latest]
    if not losers:
        # Bütün qaçışlar eyni anda başlayıb -> sıralama yoxdur, müstəqil cəhdlər.
        return _collect(case_id, pool, cross_dataset)

    winner_origin = [g[0].origin for g in winners][-1]
    for group, origin in losers:
        outcome.superseded.append(
            SupersededEntry(
                case_id=case_id,
                origin=origin,
                superseded_by=winner_origin,
                n_items=len(group),
            )
        )
    return _collect(case_id, winners, cross_dataset)


def _collect(case_id: str, pool: list[list[MergeItem]], cross_dataset: bool) -> MergedCase:
    groups = sorted(pool, key=lambda g: (g[0].origin.moment or datetime.min.replace(
        tzinfo=timezone.utc), g[0].origin.run_id))
    return MergedCase(
        case_id=case_id,
        origins=[g[0].origin for g in groups],
        items=[i.payload for g in groups for i in g],
        dataset_hash=groups[-1][0].origin.dataset_hash,
        cross_dataset=cross_dataset,
    )


# ------------------------------------------------------- RunRecord birləşməsi
def origin_of(record: RunRecord, source: str = "") -> RunOrigin:
    return RunOrigin(
        run_id=record.run_id,
        started_at=record.started_at,
        dataset_hash=record.dataset_hash,
        source=source,
    )


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(round((p / 100.0) * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[idx]


def _coverage(kept: Sequence[CaseResult], sources_missing: list[str]) -> dict[str, Any]:
    """Birləşdirilmiş qeyd üçün xərc əhatəsi — BƏRPA olunmuş, dəqiq deyil.

    Mənbə qaçışların `cost_coverage` bloku BÜTÜN cəhdləri sayır (əvəz
    olunanları da). Birləşmədən sonra qalan nəticələr üçün cəhd sayı
    `CaseResult`-dan yenidən yığılır; `reconstructed: true` bunu gizlətmir.
    """
    unmeasured = sum(r.unmeasured_attempts for r in kept)
    measured = sum(max(r.attempt, 1) for r in kept if r.cost_usd is not None)
    attempts = measured + unmeasured
    if attempts and unmeasured == 0:
        status = COMPLETE
    elif measured == 0:
        status = UNMEASURED
    else:
        status = PARTIAL
    note = (
        "birləşdirilmiş qeyd: cəhd sayı QALİB nəticələrdən bərpa olunub, "
        "mənbə qaçışların öz sayğacı deyil"
    )
    if sources_missing:
        note += (
            " · bu mənbələrdə `cost_coverage` bloku ümumiyyətlə yox idi "
            f"(köhnə sxem): {', '.join(sources_missing)}"
        )
    if unmeasured:
        note += (
            " · bəzi uğursuz cəhdlər `usage` qaytarmadı — onların xərci "
            "NAMƏLUMDUR (sıfır deyil)"
        )
    return {
        "attempts": attempts,
        "measured_attempts": measured,
        "unmeasured_attempts": unmeasured,
        "status": status,
        "note": note,
        "direction": "understates" if unmeasured else "exact",
        "reconstructed": True,
    }


def merge_records(
    records: Sequence[RunRecord],
    *,
    sources: Sequence[str] = (),
    fingerprints: Sequence[dict[str, str]] | None = None,
    allow_cross_dataset: bool = False,
    supersede: bool = True,
) -> tuple[RunRecord, MergeOutcome]:
    """Bir neçə RunRecord -> TƏK, əvəzləmələri həll edilmiş RunRecord.

    Rəqəmlər (keçmə dərəcəsi, xərc, gecikmə) YALNIZ qalib nəticələrə görə
    yenidən hesablanır: baseline gələcək TƏK qaçışla müqayisə olunacaq, ona
    görə əvəz olunmuş cəhdlərin xərci ümumi məbləğə qatılmır. Həmin məbləğ
    itmir — `totals["merge"]["spent_including_superseded_usd"]`-də qalır.
    """
    if not records:
        raise ValueError("birləşdiriləcək RunRecord yoxdur")
    from agentproof.failure import reason_for_response
    from agentproof.graders.calibration import judge_status

    labels = list(sources) + [""] * (len(records) - len(sources))
    origins = [origin_of(rec, label) for rec, label in zip(records, labels)]

    # Case TƏRİFİNİN barmaq izi RunRecord-da YOXDUR — `.eval` logundan gəlir
    # (`normalize.read_case_fingerprints`). Verilməyəndə boş qalır və fərqli
    # `dataset_hash`-lı birləşmə "yoxlanmadı" kimi işarələnir.
    prints = list(fingerprints or []) + [{}] * len(records)
    items = [
        MergeItem(
            case_id=result.case_id,
            origin=origin,
            payload=result,
            fingerprint=marks.get(result.case_id, ""),
        )
        for record, origin, marks in zip(records, origins, prints)
        for result in record.results
    ]
    outcome = merge_items(
        items, supersede=supersede, allow_cross_dataset=allow_cross_dataset
    )

    kept: list[CaseResult] = [r for case in outcome.cases for r in case.items]
    superseded_ids = {e.case_id for e in outcome.superseded}

    graded = [r for r in kept if not r.grade.skipped]
    latencies = [float(r.latency_ms) for r in kept if r.latency_ms > 0]
    costs = [r.cost_usd for r in kept if r.cost_usd is not None]
    skipped_by_reason: dict[str, int] = {}
    for r in kept:
        if r.grade.skipped:
            reason = reason_for_response(r.response) or "unknown"
            skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1

    ordered = sorted(
        zip(records, origins),
        key=lambda pair: (
            pair[1].moment or datetime.min.replace(tzinfo=timezone.utc),
            pair[1].run_id,
        ),
    )
    newest, newest_origin = ordered[-1]

    missing_coverage = [
        o.run_id or o.source or "?"
        for rec, o in zip(records, origins)
        if not (rec.totals or {}).get("cost_coverage")
    ]

    spent = 0.0
    for record in records:
        spent += float((record.totals or {}).get("cost_usd") or 0.0)
        spent += float((record.totals or {}).get("wasted_cost_usd") or 0.0)

    # Birləşmiş qeydin `dataset_hash`-i: case dəstini TAM ƏHATƏ EDƏN mənbənin
    # imzası. `full-run-03` (162 case) + `full-run-03b` (həmin 25-in təkrarı)
    # halında bu, 162-lik qaçışın imzasıdır — "ən son qaçış" olan 25-liyinki
    # yox, çünki o, dəstin yalnız altıda birini imzalayır.
    kept_ids = {r.case_id for r in kept}
    covering = [
        (rec, o)
        for rec, o in ordered
        if kept_ids <= {r.case_id for r in rec.results}
    ]
    hash_origin = covering[-1][1] if covering else newest_origin
    hashes = sorted({o.dataset_hash for o in origins})
    if len(hashes) > 1:
        outcome.warnings.append(
            "birləşdirilmiş qeydin `dataset_hash`-i "
            + (
                f"case dəstini tam əhatə edən qaçışdan götürüldü ({hash_origin.dataset_hash or '?'})"
                if covering
                else f"ƏN SON qaçışdan götürüldü ({hash_origin.dataset_hash or '?'}) — "
                "mənbələrin heç biri birləşmiş case dəstini TƏK BAŞINA əhatə etmir"
            )
            + f"; mənbələrdə: {', '.join(h or '?' for h in hashes)}. "
            "Bu qeyd BİR dataset imzasını daşımır — müqayisə edərkən "
            "`totals['merge']['sources']`-a bax."
        )

    still_skipped = [r.case_id for r in kept if r.grade.skipped]
    halted_sources = [
        (rec.totals or {}).get("halted") or {}
        for rec in records
        if ((rec.totals or {}).get("halted") or {}).get("halted")
    ]
    if halted_sources and still_skipped:
        halted = dict(halted_sources[-1])
    else:
        halted = {
            "halted": False,
            "reason": "",
            "detail": (
                f"{len(halted_sources)} mənbə qaçış yarıda dayandırılmışdı; "
                "sonrakı qaçış(lar) qalan case-ləri ölçdü, birləşmədən sonra "
                "ölçülməmiş case qalmadı"
                if halted_sources
                else ""
            ),
            "case_id": "",
            "hint": "",
        }

    totals: dict[str, Any] = {
        "n_cases": len(kept),
        "n_graded": len(graded),
        "n_passed": sum(1 for r in graded if r.grade.passed),
        "n_failed": sum(1 for r in graded if not r.grade.passed),
        "n_skipped": len(kept) - len(graded),
        "skipped_by_reason": skipped_by_reason,
        "pass_rate": (sum(1 for r in graded if r.grade.passed) / len(graded)) if graded else 0.0,
        "cost_usd": sum(costs),
        "wasted_cost_usd": sum(r.wasted_cost_usd for r in kept),
        "cost_coverage": _coverage(kept, missing_coverage),
        "halted": halted,
        "p50_latency_ms": _percentile(latencies, 50),
        "p95_latency_ms": _percentile(latencies, 95),
        "multi_turn_cases": sum(1 for r in kept if r.response.n_turns > 1),
        "judge": judge_status(r.grade.grader for r in kept),
        "baseline_tagged": _tag_summary(kept, BASELINE_TAG),
        "merge": {
            "sources": [
                {
                    **o.to_dict(),
                    "schema_version": rec.schema_version,
                    "n_results": len(rec.results),
                }
                for rec, o in zip(records, origins)
            ],
            "supersede": supersede,
            "allow_cross_dataset": allow_cross_dataset,
            "case_fingerprints_verified": bool(fingerprints),
            "n_superseded": outcome.n_superseded,
            "superseded_case_ids": sorted(superseded_ids),
            "superseded": [e.to_dict() for e in outcome.superseded],
            "warnings": list(outcome.warnings),
            "dataset_hashes": hashes,
            "dataset_hash_from": hash_origin.run_id,
            # Faktiki ödənilən məbləğ: əvəz olunmuş cəhdlərin xərci də daxil.
            # `cost_usd` bunu GÖSTƏRMİR (o, qalib nəticələrin xərcidir) — iki
            # rəqəm iki fərqli suala cavab verir.
            "spent_including_superseded_usd": round(spent, 6),
        },
    }
    # Yalnız ƏN SON qaçışdan gələn provenans blokları (hədəf konfiqurasiyası).
    for key in ("price_table_as_of", "priced_on", "model_check", "lanes",
                "anchor_check", "retrieval_check"):
        value = (newest.totals or {}).get(key)
        if value is not None:
            totals[key] = value

    merged = RunRecord(
        run_id=_merged_run_id(origins),
        target=newest.target,
        target_version=newest.target_version,
        model=newest.model,
        dataset_hash=hash_origin.dataset_hash,
        started_at=newest.started_at,
        results=kept,
        totals=totals,
        schema_version=max(rec.schema_version for rec in records) or SCHEMA_VERSION,
        embedding_model=newest.embedding_model,
        embedding_provider=newest.embedding_provider,
        effective_top_k=newest.effective_top_k,
        reranking_enabled=newest.reranking_enabled,
    )
    return merged, outcome


def _tag_summary(kept: Sequence[CaseResult], tag: str) -> dict[str, Any]:
    group = [r for r in kept if tag in (r.tags or [])]
    graded = [r for r in group if not r.grade.skipped]
    failing = sorted(r.case_id for r in graded if not r.grade.passed)
    return {
        "tag": tag,
        "n": len(group),
        "n_graded": len(graded),
        "n_passed": len(graded) - len(failing),
        "n_failed": len(failing),
        "n_skipped": len(group) - len(graded),
        "pass_rate": (len(graded) - len(failing)) / len(graded) if graded else 0.0,
        "failing_case_ids": failing,
    }


def _merged_run_id(origins: Iterable[RunOrigin]) -> str:
    """Mənbələrdən DETERMİNİST id — eyni girişlər eyni id verir."""
    payload = "|".join(sorted(f"{o.run_id}@{o.started_at}" for o in origins))
    return "merge-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def render_merge_notes(outcome: MergeOutcome) -> str:
    """İnsan üçün: nə əvəz olundu, nə xəbərdarlıq var."""
    lines: list[str] = []
    if outcome.superseded:
        lines.append(
            f"Əvəz olunmuş nəticə: {outcome.n_superseded} "
            f"({len({e.case_id for e in outcome.superseded})} case) — SİLİNMƏDİ, qeyd olundu"
        )
        for entry in outcome.superseded[:10]:
            lines.append(
                f"  - {entry.case_id}: {entry.origin.label} -> {entry.superseded_by.label}"
            )
        if len(outcome.superseded) > 10:
            lines.append(f"  - … və daha {len(outcome.superseded) - 10} nəticə")
    if outcome.warnings:
        lines.append("XƏBƏRDARLIQ:")
        lines += [f"  ! {w}" for w in outcome.warnings]
    return "\n".join(lines)

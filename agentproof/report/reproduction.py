"""Reproduksiya qapısı — PLAN.md Keyfiyyət qaydası #1-in maşınla tətbiqi.

    "Reproduksiya olunmayan tapıntı hesabata düşmür. Bir dəfə baş verib
     təkrarlanmayan hal ayrıca 'flaky' kimi qeyd olunur."

`--repeat N` ilə qaçırılmış hər case üçün N müstəqil cavab var. Bu modul HƏR
CƏHDİ AYRICA qiymətləndirib case-i səbətlərə bölür:

  stable-pass    — bütün cəhdlərdə keçdi
  stable-fail    — bütün cəhdlərdə EYNİ səbəblə sındı → FINDINGS.md namizədi
  unstable-fail  — bütün cəhdlərdə sındı, amma FƏRQLİ səbəblərlə. Bu, stabil
                   tapıntı DEYİL: "hər dəfə sınır" ilə "hər dəfə eyni şey
                   sınır" fərqli iddialardır, ikincisi olmadan tapıntının
                   səbəbi yazıla bilməz.
  flaky          — qarışıq nəticə (1/3, 2/3) → DƏRC OLUNMUR, ayrıca siyahı
  incomplete     — cəhdlərin bir hissəsi qiymətləndirilə bilmədi (infra xətası,
                   yarımçıq qaçış) → 3/3 reproduksiya sübutu YOXDUR
  skipped        — heç bir cəhd qiymətləndirilmədi (aqreqat/judge grader,
                   tam infra xətası)

Niyə `normalize_log()` bəs etmir: o, `--repeat 3` qaçışında da hər case üçün
TƏK verdikt saxlayır (sonuncu cavabın verdikti, `attempt=3` sahəsi ilə). Yəni
RunRecord-un özündə cəhd-səviyyəli nəticə YOXDUR. Ona görə əsl təsnifat mənbəyi
`.eval` logudur (`normalize.repeat_responses`) və RunRecord yolu bunu susmaqla
"hamısı stabildir"ə çevirmək əvəzinə açıq şəkildə etiraf edir.

Bu modul `inspect_ai` import ETMİR (STACK.md §6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from agentproof.graders import registry
from agentproof.report.merge import (
    MergeItem,
    MergeOutcome,
    RunOrigin,
    SupersededEntry,
    fingerprint_case,
    merge_items,
    origin_of,
)
from agentproof.types import AgentResponse, Case, RunRecord

STABLE_PASS = "stable-pass"
STABLE_FAIL = "stable-fail"
UNSTABLE_FAIL = "unstable-fail"
FLAKY = "flaky"
INCOMPLETE = "incomplete"
SKIPPED = "skipped"

#: Yalnız bu səbətdən FINDINGS.md-ə tapıntı götürülə bilər (AP-007 DoD).
PUBLISHABLE = (STABLE_FAIL,)

#: Bundan yuxarı flaky nisbəti ölçmənin ÖZÜNÜN etibarsız olduğunu göstərir.
FLAKY_ALARM = 0.10

_ORDER = (STABLE_PASS, STABLE_FAIL, UNSTABLE_FAIL, FLAKY, INCOMPLETE, SKIPPED)

#: Təsnifat həqiqətən aparılmış case-lər (məxrəc: flaky nisbəti bunlara görədir)
_CLASSIFIED = (STABLE_PASS, STABLE_FAIL, UNSTABLE_FAIL, FLAKY)


# --------------------------------------------------------------------- tiplər
@dataclass(frozen=True)
class Attempt:
    """Bir `--repeat` cəhdinin nəticəsi."""

    passed: bool
    skipped: bool = False
    reason: str = ""
    grader: str = ""

    @property
    def signature(self) -> str:
        """Səbəb imzası — "eyni səbəblə sındı" müqayisəsi bununla aparılır.

        Yalnız boşluq/registr normallaşdırılır: rəqəmləri və ifadələri
        silsək, FƏRQLİ uğursuzluqlar eyni görünərdi (məhz gizlətmək
        istəmədiyimiz hal).
        """
        return f"{self.grader}::{' '.join(self.reason.split()).lower()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "skipped": self.skipped,
            "reason": self.reason,
            "grader": self.grader,
        }


@dataclass
class CaseVerdict:
    case_id: str
    classification: str
    attempts: list[Attempt] = field(default_factory=list)
    grader: str = ""
    severity: str = "medium"
    tags: list[str] = field(default_factory=list)
    note: str = ""

    # --- mənşə (AP-042): bu verdikt HANSI qaçışdan gəldi ------------------
    run_id: str = ""
    started_at: str = ""
    dataset_hash: str = ""
    cross_dataset: bool = False
    """Eyni `case_id` başqa `dataset_hash` altında da var — birləşdirilmədi."""

    @property
    def n_attempts(self) -> int:
        return len(self.attempts)

    @property
    def graded(self) -> list[Attempt]:
        return [a for a in self.attempts if not a.skipped]

    @property
    def n_passed(self) -> int:
        return sum(1 for a in self.graded if a.passed)

    @property
    def n_failed(self) -> int:
        return sum(1 for a in self.graded if not a.passed)

    @property
    def n_skipped(self) -> int:
        return sum(1 for a in self.attempts if a.skipped)

    @property
    def publishable(self) -> bool:
        """Bu case FINDINGS.md-ə düşə bilərmi."""
        return self.classification in PUBLISHABLE

    @property
    def reason_variants(self) -> list[str]:
        """Sınmış cəhdlərdə görünən TƏKRARSIZ səbəblər (görünmə sırası ilə)."""
        seen: dict[str, str] = {}
        for a in self.graded:
            if not a.passed:
                seen.setdefault(a.signature, a.reason)
        return list(seen.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "classification": self.classification,
            "publishable": self.publishable,
            "grader": self.grader,
            "severity": self.severity,
            "tags": self.tags,
            "n_attempts": self.n_attempts,
            "n_passed": self.n_passed,
            "n_failed": self.n_failed,
            "n_skipped": self.n_skipped,
            "reason_variants": self.reason_variants,
            "note": self.note,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "dataset_hash": self.dataset_hash,
            "cross_dataset": self.cross_dataset,
            "attempts": [a.to_dict() for a in self.attempts],
        }


@dataclass
class ReproductionReport:
    verdicts: list[CaseVerdict] = field(default_factory=list)
    repeats: int = 1
    """Müşahidə olunan ƏN ÇOX cəhd sayı (yəni qaçışın faktiki `--repeat`-i)."""

    classifiable: bool = True
    """`False` olanda təsnifat APARILMAYIB — nəticələr "stabil" kimi oxunmamalıdır."""

    notice: str = ""
    source: str = ""

    superseded: list[SupersededEntry] = field(default_factory=list)
    """Əvəz olunmuş (amma SİLİNMƏMİŞ) nəticələr — AP-042.

    Bunlar `verdicts`-ə DAXİL DEYİL: case bir dəfə sayılır. Amma artefaktdan
    da atılmır — "bu case iki dəfə ölçüldü, ikincisini götürdük" auditorun
    görməli olduğu faktdır.
    """

    warnings: list[str] = field(default_factory=list)
    """Birləşmə xəbərdarlıqları (fərqli `dataset_hash`, tarixsiz qaçış, ...)."""

    # ------------------------------------------------------------- sayğaclar
    @property
    def n_superseded(self) -> int:
        return sum(e.n_items for e in self.superseded)

    @property
    def counts(self) -> dict[str, int]:
        out = {k: 0 for k in _ORDER}
        for v in self.verdicts:
            out[v.classification] = out.get(v.classification, 0) + 1
        return out

    @property
    def n_classified(self) -> int:
        return sum(1 for v in self.verdicts if v.classification in _CLASSIFIED)

    @property
    def flaky_rate(self) -> float | None:
        """Flaky / təsnif olunmuş case. Məxrəc 0-dırsa `None` — 0.0 DEYİL.

        0.0 qaytarmaq "flaky yoxdur, hər şey qaydasındadır" kimi oxunardı;
        halbuki heç nə ölçülməyib.
        """
        if not self.n_classified:
            return None
        return self.counts[FLAKY] / self.n_classified

    @property
    def flaky_alarm(self) -> bool:
        rate = self.flaky_rate
        return rate is not None and rate > FLAKY_ALARM

    def by_class(self, name: str) -> list[CaseVerdict]:
        return [v for v in self.verdicts if v.classification == name]

    @property
    def findings(self) -> list[CaseVerdict]:
        """FINDINGS.md-ə düşə bilən YEGANƏ siyahı."""
        return [v for v in self.verdicts if v.publishable]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "source": self.source,
            "repeats": self.repeats,
            "classification_possible": self.classifiable,
            "notice": self.notice,
            "counts": self.counts,
            "n_cases": len(self.verdicts),
            "n_classified": self.n_classified,
            "flaky_rate": self.flaky_rate,
            "flaky_alarm": self.flaky_alarm,
            "publishable_case_ids": [v.case_id for v in self.findings],
            # AP-042: əvəz olunan nəticələr silinmir — sayı və mənşəyi qalır.
            "n_superseded": self.n_superseded,
            "superseded": [e.to_dict() for e in self.superseded],
            "merge_warnings": list(self.warnings),
            "cases": [v.to_dict() for v in self.verdicts],
        }


# ----------------------------------------------------------------- təsnifat
def classify_attempts(attempts: Sequence[Attempt], expected: int = 0) -> tuple[str, str]:
    """Cəhd siyahısı → `(təsnifat, qeyd)`.

    `expected`: qaçışın gözlənilən təkrar sayı. Case bundan az cəhdlə
    ölçülübsə, 3/3 reproduksiya sübutu yoxdur → `incomplete`.
    """
    graded = [a for a in attempts if not a.skipped]
    if not graded:
        return SKIPPED, "heç bir cəhd qiymətləndirilmədi"
    if len(graded) < len(attempts):
        return INCOMPLETE, (
            f"{len(attempts) - len(graded)}/{len(attempts)} cəhd qiymətləndirilmədi — "
            "tam reproduksiya sübutu yoxdur"
        )
    if expected and len(attempts) < expected:
        return INCOMPLETE, (
            f"yalnız {len(attempts)} cəhd var, qaçış {expected} təkrarlıdır"
        )
    if len(graded) < 2:
        return INCOMPLETE, "tək cəhd — təkrarlanma yoxlanıla bilmir"

    outcomes = {a.passed for a in graded}
    if len(outcomes) > 1:
        return FLAKY, (
            f"{sum(1 for a in graded if a.passed)}/{len(graded)} keçdi — "
            "təkrarlanmır, tapıntı kimi dərc olunmur"
        )
    if outcomes.pop():
        return STABLE_PASS, ""

    signatures = {a.signature for a in graded}
    if len(signatures) > 1:
        return UNSTABLE_FAIL, (
            f"{len(graded)}/{len(graded)} sındı, amma {len(signatures)} FƏRQLİ səbəblə — "
            "stabil tapıntı deyil, səbəb reproduksiya olunmayıb"
        )
    return STABLE_FAIL, ""


def _finish(
    verdicts: list[CaseVerdict],
    source: str,
    classifiable: bool = True,
    notice: str = "",
    outcome: MergeOutcome | None = None,
) -> ReproductionReport:
    repeats = max((v.n_attempts for v in verdicts), default=0)
    return ReproductionReport(
        verdicts=verdicts,
        repeats=repeats,
        classifiable=classifiable,
        notice=notice,
        source=source,
        superseded=list(outcome.superseded) if outcome else [],
        warnings=list(outcome.warnings) if outcome else [],
    )


# --------------------------------------------------- mənbə 1: `.eval` log
def grade_repeats(case: Case, responses: Sequence[AgentResponse]) -> tuple[list[Attempt], str]:
    """Hər cavabı AYRICA qiymətləndir → cəhd-səviyyəli verdiktlər.

    Qaytarır: `(cəhdlər, qeyd)`. Qeyd boş deyilsə, case bölünə bilməyib.
    """
    name = case.grader
    try:
        grader = registry.get(name)
    except KeyError as e:
        return [], f"grader tapılmadı: {e}"
    if registry.is_aggregate(name):
        return [], (
            f"aqreqat grader `{name}` — k cavab onsuz da TƏK verdikt verir, "
            "cəhdlərə bölünə bilməz"
        )
    if registry.kind(name) == "judge":
        return [], (
            f"judge grader `{name}` — oflayn yenidən qiymətləndirilmir "
            "(şəbəkə tələb edir); reproduksiya qapısı bu case-i təsnif etmir"
        )

    attempts: list[Attempt] = []
    for response in responses:
        if response.error:
            attempts.append(
                Attempt(
                    passed=False,
                    skipped=True,
                    reason=f"hədəf infrastruktur xətası: {response.error}",
                    grader=name,
                )
            )
            continue
        try:
            result = grader.grade(case, response)  # type: ignore[union-attr]
        except Exception as exc:  # dataset/grader xətası case-i gizlətməməlidir
            attempts.append(
                Attempt(passed=False, skipped=True, reason=f"grader xətası: {exc}", grader=name)
            )
            continue
        attempts.append(
            Attempt(
                passed=result.passed and not result.skipped,
                skipped=result.skipped,
                reason=result.reason,
                grader=name,
            )
        )
    return attempts, ""


def from_log_samples(
    samples: Iterable[Sequence[Any]],
    source: str = "",
    *,
    supersede: bool = True,
    allow_cross_dataset: bool = False,
) -> ReproductionReport:
    """`normalize.repeat_responses()` çıxışını təsnif edir.

    Element ya `(meta, responses)`, ya da `(meta, responses, RunOrigin)` olur.
    Mənşə verilməyəndə bütün nümunələr eyni (boş) qaçışdan sayılır — tək logu
    oxuyan köhnə çağırışlar üçün davranış dəyişmir.

    AP-042: bir neçə log birlikdə oxunanda eyni `case_id` İKİ DƏFƏ SAYILMIR —
    ən son qaçışın nəticəsi götürülür, əvvəlki `superseded` kimi qeyd olunur.
    """
    items: list[MergeItem] = []
    for entry in samples:
        meta, responses = entry[0], entry[1]
        origin = entry[2] if len(entry) > 2 else RunOrigin()
        meta = dict(meta)
        items.append(
            MergeItem(
                case_id=str(meta.get("id", "")),
                origin=origin,
                payload=(meta, list(responses)),
                fingerprint=fingerprint_case(meta),
            )
        )

    outcome = merge_items(
        items, supersede=supersede, allow_cross_dataset=allow_cross_dataset
    )
    expected = max(
        (sum(len(responses) for _, responses in case.items) for case in outcome.cases),
        default=0,
    )

    verdicts: list[CaseVerdict] = []
    for merged in outcome.cases:
        meta, _ = merged.items[0]
        case = Case.from_dict(meta)
        attempts: list[Attempt] = []
        note = ""
        for _, responses in merged.items:
            got, why = grade_repeats(case, responses)
            if why:
                note = why
                break
            attempts += got
        if note:
            classification = SKIPPED
        else:
            classification, note = classify_attempts(attempts, expected=expected)
        verdicts.append(
            CaseVerdict(
                case_id=case.id,
                classification=classification,
                attempts=attempts,
                grader=case.grader,
                severity=case.severity,
                tags=list(case.tags),
                note=note,
                run_id=merged.origin.run_id,
                started_at=merged.origin.started_at,
                dataset_hash=merged.dataset_hash,
                cross_dataset=merged.cross_dataset,
            )
        )

    if expected < 2:
        return _finish(
            verdicts,
            source,
            classifiable=False,
            notice=(
                "TƏKRAR YOXDUR (hər case üçün ən çoxu 1 cavab var) — təsnifat mümkün "
                "deyil. `--repeat 3` ilə qaçır; bu nəticələr 'stabil' kimi oxunmamalıdır."
            ),
            outcome=outcome,
        )
    return _finish(verdicts, source, outcome=outcome)


# ------------------------------------------------ mənbə 2: RunRecord JSON
def from_records(
    records: Sequence[RunRecord],
    source: str = "",
    *,
    sources: Sequence[str] = (),
    supersede: bool = True,
    allow_cross_dataset: bool = False,
) -> ReproductionReport:
    """Bir və ya bir neçə RunRecord-u case üzrə birləşdirib təsnif edir.

    RunRecord-da hər case üçün BİR verdikt var. Yəni:
      * N ayrı RunRecord (N müstəqil qaçış) → N cəhd, təsnifat MÜMKÜN;
      * tək RunRecord, `--repeat` verilməyib → 1 cəhd, təsnifat MÜMKÜN DEYİL;
      * tək RunRecord, `--repeat 3` → yenə 1 verdikt (`attempt=3`), çünki
        `normalize_log()` cəhdləri birləşdirir. Bu hal SUSMAQLA "stabil"
        sayılmır — açıq şəkildə etiraf olunur və `.eval` logu tələb edilir.

    AP-042 əvəzləməsi: eyni `case_id` bir neçə qaçışda varsa, ƏN SON
    (`started_at`) qaçışın nəticəsi götürülür və əvvəlkilər `superseded`
    olur. Qaçışların tarixi EYNİ olanda sıralama yoxdur — onda hamısı cəhd
    kimi qalır (yuxarıdakı "N müstəqil qaçış" halı). `supersede=False`
    əvəzləməni tamamilə söndürür.
    """
    labels = list(sources) + [""] * max(0, len(records) - len(sources))
    items = [
        MergeItem(case_id=result.case_id, origin=origin_of(record, label), payload=result)
        for record, label in zip(records, labels)
        for result in record.results
    ]
    outcome = merge_items(
        items, supersede=supersede, allow_cross_dataset=allow_cross_dataset
    )

    expected = max((len(case.items) for case in outcome.cases), default=0)
    verdicts: list[CaseVerdict] = []
    collapsed: list[str] = []
    for merged in outcome.cases:
        results = merged.items
        attempts = [
            Attempt(
                passed=r.grade.passed and not r.grade.skipped,
                skipped=r.grade.skipped,
                reason=r.grade.reason,
                grader=r.grade.grader,
            )
            for r in results
        ]
        if len(results) == 1 and results[0].attempt > 1:
            collapsed.append(merged.case_id)
        classification, note = classify_attempts(attempts, expected=expected)
        verdicts.append(
            CaseVerdict(
                case_id=merged.case_id,
                classification=classification,
                attempts=attempts,
                grader=results[0].grade.grader,
                severity=results[0].severity,
                tags=list(results[0].tags),
                note=note,
                run_id=merged.origin.run_id,
                started_at=merged.origin.started_at,
                dataset_hash=merged.dataset_hash,
                cross_dataset=merged.cross_dataset,
            )
        )

    n_attempts = max((v.n_attempts for v in verdicts), default=0)
    if collapsed:
        return _finish(
            verdicts,
            source,
            classifiable=False,
            notice=(
                f"RunRecord təkrarları BİRLƏŞDİRİB: {len(collapsed)} case-də `attempt` > 1, "
                "amma verdikt tək. Cəhd-səviyyəli təsnifat üçün `.eval` logu lazımdır "
                "(`python evals/reproduce.py reports/<qaçış>/logs/*.eval`). "
                "Bu nəticələr 'stabil' kimi oxunmamalıdır."
            ),
            outcome=outcome,
        )
    if n_attempts < 2:
        return _finish(
            verdicts,
            source,
            classifiable=False,
            notice=(
                "TƏKRAR YOXDUR (hər case üçün 1 nəticə) — təsnifat mümkün deyil. "
                "`--repeat 3` ilə qaçır və ya bir neçə RunRecord ver; bu nəticələr "
                "'stabil' kimi oxunmamalıdır."
            ),
            outcome=outcome,
        )
    return _finish(verdicts, source, outcome=outcome)


# ------------------------------------------- mənbə 3: saxlanmış reproduction.json
def report_from_dict(data: dict[str, Any]) -> ReproductionReport:
    """`to_dict()`-in tərsi — saxlanmış `reproduction.json` yenidən oxunur.

    Hesabat qatı (`report/html.py`) təsnifatı YENİDƏN APARMIR: qapı bir dəfə
    `evals/reproduce.py` ilə qaçır, nəticəsi artefakt kimi saxlanılır. Səhifə
    həmin artefakti oxuyur ki, hesabatda görünən təsnifat qapının verdiyi
    təsnifatla eyni olsun — iki fərqli yerdə hesablanan iki fərqli rəqəm
    auditdə müdafiə olunmur.
    """
    verdicts = [
        CaseVerdict(
            case_id=str(c.get("case_id", "")),
            classification=str(c.get("classification", SKIPPED)),
            attempts=[
                Attempt(
                    passed=bool(a.get("passed", False)),
                    skipped=bool(a.get("skipped", False)),
                    reason=str(a.get("reason", "")),
                    grader=str(a.get("grader", "")),
                )
                for a in c.get("attempts", [])
            ],
            grader=str(c.get("grader", "")),
            severity=str(c.get("severity", "medium")),
            tags=list(c.get("tags", [])),
            note=str(c.get("note", "")),
        )
        for c in data.get("cases", [])
    ]
    superseded = [
        SupersededEntry(
            case_id=str(e.get("case_id", "")),
            origin=_origin_from_dict(e.get("origin")),
            superseded_by=_origin_from_dict(e.get("superseded_by")),
            n_items=int(e.get("n_items", 1) or 1),
        )
        for e in data.get("superseded", [])
    ]
    return ReproductionReport(
        verdicts=verdicts,
        repeats=int(data.get("repeats", 0)),
        classifiable=bool(data.get("classification_possible", True)),
        notice=str(data.get("notice", "")),
        source=str(data.get("source", "")),
        superseded=superseded,
        warnings=list(data.get("merge_warnings", [])),
    )


def _origin_from_dict(d: Any) -> RunOrigin:
    d = d or {}
    return RunOrigin(
        run_id=str(d.get("run_id", "")),
        started_at=str(d.get("started_at", "")),
        dataset_hash=str(d.get("dataset_hash", "")),
        source=str(d.get("source", "")),
    )


# ------------------------------------------------------------------ çıxış
def _pct(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate:.1%}"


def flaky_headline(report: ReproductionReport) -> str:
    """Flaky nisbəti — hesabatın ƏN GÖRÜNƏN sətri (AP-007 tələb 2)."""
    rate = report.flaky_rate
    if rate is None:
        return "FLAKY NİSBƏTİ: n/a — heç bir case təsnif olunmadı"
    head = (
        f"FLAKY NİSBƏTİ: {_pct(rate)} "
        f"({report.counts[FLAKY]} / {report.n_classified} təsnif olunmuş case)"
    )
    if report.flaky_alarm:
        head += (
            f"  ⚠️ HƏDD {FLAKY_ALARM:.0%} AŞILDI — bu qaçışda ölçmənin ÖZÜ etibarsızdır"
        )
    return head


def _superseded_suffix(report: ReproductionReport) -> str:
    n = report.n_superseded
    return f" · əvəz olunmuş nəticə: {n}" if n else ""


def _warning_lines(report: ReproductionReport) -> list[str]:
    if not report.warnings:
        return []
    return ["BİRLƏŞMƏ XƏBƏRDARLIĞI:", *(f"  ! {w}" for w in report.warnings), ""]


def _case_lines(verdicts: Sequence[CaseVerdict], limit: int = 20) -> list[str]:
    lines = []
    for v in verdicts[:limit]:
        detail = v.reason_variants[0] if v.reason_variants else v.note
        lines.append(
            f"  - {v.case_id} [{v.severity}] ({v.grader}) "
            f"{v.n_passed}/{len(v.graded) or v.n_attempts} keçdi — {detail}"
        )
        for extra in v.reason_variants[1:]:
            lines.append(f"      · digər səbəb: {extra}")
    if len(verdicts) > limit:
        lines.append(f"  - … və daha {len(verdicts) - limit} case")
    return lines


def render_text(report: ReproductionReport) -> str:
    """İnsan üçün mətn xülasə."""
    out: list[str] = []
    title = "Reproduksiya qapısı (PLAN.md keyfiyyət qaydası #1)"
    if report.source:
        title += f" — {report.source}"
    out += [title, "=" * len(title), ""]

    if not report.classifiable:
        out += [
            "TƏSNİFAT APARILMADI.",
            f"  {report.notice}",
            "",
            f"Case sayı: {len(report.verdicts)} · müşahidə olunan təkrar: {report.repeats}"
            + _superseded_suffix(report),
            "",
            "Heç bir case 'stabil' sayılmır; FINDINGS.md üçün namizəd YOXDUR.",
            *_warning_lines(report),
        ]
        return "\n".join(out)

    counts = report.counts
    out += [
        flaky_headline(report),
        "",
        f"Təkrar: {report.repeats} · case: {len(report.verdicts)}"
        + _superseded_suffix(report),
        "",
        f"  stable-pass    {counts[STABLE_PASS]:>4}",
        f"  stable-fail    {counts[STABLE_FAIL]:>4}   <- YALNIZ bu səbət FINDINGS.md-ə düşə bilər",
        f"  unstable-fail  {counts[UNSTABLE_FAIL]:>4}   (hər dəfə sındı, amma fərqli səbəblə)",
        f"  flaky          {counts[FLAKY]:>4}   (DƏRC OLUNMUR)",
        f"  incomplete     {counts[INCOMPLETE]:>4}",
        f"  skipped        {counts[SKIPPED]:>4}",
        # Əvəz olunanlar case sayına DAXİL DEYİL (yoxsa yenə ikiqat sayılardı),
        # amma gizlədilmir də — hansı nəticənin götürülmədiyi auditin faktıdır.
        f"  superseded     {report.n_superseded:>4}   (əvəz olundu — silinmədi, sayılır)",
        "",
    ]
    out += _warning_lines(report)
    if report.notice:
        out += [report.notice, ""]

    sections = [
        (STABLE_FAIL, "Stabil tapıntı namizədləri (stable-fail) — dərc oluna bilər"),
        (UNSTABLE_FAIL, "Fərqli səbəblərlə sınanlar (unstable-fail) — dərc OLUNMUR"),
        (FLAKY, "Flaky — dərc OLUNMUR, ayrıca qeyd"),
        (INCOMPLETE, "Yarımçıq ölçülənlər (incomplete)"),
        (SKIPPED, "Qiymətləndirilməyənlər (skipped)"),
    ]
    for name, heading in sections:
        group = report.by_class(name)
        if not group:
            continue
        out += [f"{heading} — {len(group)}", *_case_lines(group), ""]

    out += [flaky_headline(report)]
    return "\n".join(out)

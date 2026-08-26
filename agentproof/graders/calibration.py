"""Judge kalibrasiyası — insan etiketi ilə uyğunluq və Cohen's kappa.

POZULMAZ QAYDA: bu modul `inspect_ai` import ETMİR (STACK.md §6).

Niyə bu modul var
-----------------
Kalibrasiya edilməmiş judge nəticəsi elmi zibildir və pullu auditdə müdafiə
olunmur (grader-eng.md). Bütün müasir çərçivələr LLM-judge üzərində qurulub,
lakin judge-un öz yanlılığını ölçmür — FAILURE-TAXONOMY.md §10 Boşluq 7.
Bizim hesabatın fərqi budur: **öz etibarlılığını sübut edən bölmə.**

Xam faiz kifayət deyil
----------------------
Üç sinifli dəstdə həmişə eyni verdikti verən "null model" 30–35% uyğunluq alır;
sinif balansı pozulubsa bu 60%-ə də qalxa bilər. Ona görə hər hesabatda
**Cohen's kappa** da göstərilir — təsadüfi uyğunluğu çıxaran ölçü:

    kappa = (po - pe) / (1 - pe)

    po = müşahidə olunan uyğunluq
    pe = təsadüf nəticəsində gözlənilən uyğunluq (marjinal paylanmaların hasili)

Şərh (Landis & Koch): <0.20 zəif · 0.21–0.40 orta zəif · 0.41–0.60 orta ·
0.61–0.80 güclü · >0.80 çox güclü. Bizim qapı: kappa >= 0.70 VƏ uyğunluq >= 85%.

ƏSAS QAYDA — DATASET DEYİL, RUBRİKA DÜZƏLİR
-------------------------------------------
Uyğunluq 85%-dən aşağıdırsa **RUBRİKA** düzəldilir, **DATASET DEYİL**.

Etiketi judge-a uyğunlaşdırmaq kalibrasiyanı özünü təsdiqləyən mərasimə çevirir:
sonda 100% uyğunluq alırsan və heç nə ölçmüş olmursan. Etiket yalnız o halda
dəyişir ki, etiketin özündə səhv sübut olunsun (CANONICAL.yaml ilə ziddiyyət) —
və dəyişikliyin səbəbi `labeled.yaml`-ın `note` sahəsində yazılır.

Bu qayda `assert_dataset_unchanged()` ilə maşınla da qorunur: dəstin sha256-sı
hesabata yazılır, dəyişsə hesabatda AÇIQ görünür.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml

from agentproof.graders.judge import (
    VERDICTS,
    JudgeClient,
    JudgeDecision,
    JudgeProtocolError,
    JudgeRaw,
    RubricJudge,
    get_rubric,
)
from agentproof.types import Case

MIN_AGREEMENT = 0.85
"""Aşağı hədd. Keçilmirsə RUBRİKA düzəlir, dataset yox (yuxarıdakı qaydaya bax)."""

MIN_KAPPA = 0.70
"""Xam faizin gizlətdiyi təsadüfi uyğunluğa qarşı ikinci hədd."""

CALIBRATION_RULE = (
    "Uyğunluq {min_agreement:.0%}-dən aşağıdırsa RUBRİKA düzəldilir, DATASET DEYİL. "
    "Etiketi judge-a uyğunlaşdırmaq kalibrasiyanı mənasız edir."
).format(min_agreement=MIN_AGREEMENT)

DEFAULT_LABELS_PATH = Path("evals/calibration/labeled.yaml")
DEFAULT_REPORT_PATH = Path("evals/calibration/report.json")


# --------------------------------------------------------------------- dataset
@dataclass(frozen=True)
class LabeledSample:
    id: str
    scenario: str
    answer: str
    label: str
    note: str
    style: str = "neutral"
    question: str = ""
    answer_value: str = ""
    controlling_rule: str = ""
    decoy_rules: tuple[str, ...] = ()

    def to_case(self) -> Case:
        return Case(
            id=self.id,
            input=self.question,
            grader="requires_justification",
            tags=["calibration", f"style:{self.style}", f"scenario:{self.scenario}"],
            expect={
                "answer_value": self.answer_value,
                "controlling_rule": self.controlling_rule,
                "decoy_rules": list(self.decoy_rules),
            },
        )


@dataclass(frozen=True)
class CalibrationSet:
    rubric: str
    rubric_version: str
    samples: tuple[LabeledSample, ...]
    sha256: str
    path: str = ""

    def __len__(self) -> int:
        return len(self.samples)

    @property
    def label_counts(self) -> dict[str, int]:
        return dict(Counter(s.label for s in self.samples))


def load_labels(path: str | Path = DEFAULT_LABELS_PATH) -> CalibrationSet:
    """`labeled.yaml` → `CalibrationSet`. Etiket/ssenari qüsurları SƏSSİZ keçmir."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    scenarios: dict[str, dict[str, Any]] = data.get("scenarios", {})
    rubric_id = str(data.get("rubric", "requires_justification"))
    rubric = get_rubric(rubric_id)

    samples: list[LabeledSample] = []
    seen: set[str] = set()
    for raw in data.get("samples", []):
        sid = str(raw["id"])
        if sid in seen:
            raise ValueError(f"kalibrasiya dəstində təkrar id: {sid!r}")
        seen.add(sid)
        label = str(raw["label"]).strip().lower()
        if label not in rubric.verdicts:
            raise ValueError(
                f"{sid}: naməlum etiket {label!r}; rubrika '{rubric.id}' "
                f"yalnız {list(rubric.verdicts)} qəbul edir"
            )
        if not str(raw.get("note", "")).strip():
            raise ValueError(
                f"{sid}: `note` boşdur — izahsız etiket auditdə müdafiə olunmur"
            )
        scenario_id = str(raw["scenario"])
        if scenario_id not in scenarios:
            raise ValueError(f"{sid}: naməlum ssenari {scenario_id!r}")
        sc = scenarios[scenario_id]
        samples.append(
            LabeledSample(
                id=sid,
                scenario=scenario_id,
                answer=str(raw["answer"]).strip(),
                label=label,
                note=str(raw["note"]).strip(),
                style=str(raw.get("style", "neutral")),
                question=str(sc.get("question", "")).strip(),
                answer_value=str(sc.get("answer_value", "")),
                controlling_rule=str(sc.get("controlling_rule", "")).strip(),
                decoy_rules=tuple(str(d) for d in sc.get("decoy_rules", [])),
            )
        )
    if not samples:
        raise ValueError(f"{p}: kalibrasiya nümunəsi yoxdur")
    return CalibrationSet(
        rubric=rubric.id,
        rubric_version=str(data.get("rubric_version", rubric.version)),
        samples=tuple(samples),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        path=str(p),
    )


# ------------------------------------------------------------------- statistika
def agreement_rate(human: Sequence[str], judge: Sequence[str]) -> float:
    if len(human) != len(judge):
        raise ValueError(f"uzunluqlar fərqlidir: {len(human)} vs {len(judge)}")
    if not human:
        return 0.0
    return sum(1 for h, j in zip(human, judge) if h == j) / len(human)


def cohens_kappa(
    human: Sequence[str], judge: Sequence[str], labels: Iterable[str] = VERDICTS
) -> float:
    """Təsadüfi uyğunluğu çıxaran uzlaşma ölçüsü.

    Xam faiz sinif balansı pozulanda yanıldıcıdır: hər dəfə eyni verdikti verən
    judge yüksək faiz ala bilər, amma kappa-sı ~0 olur.
    """
    if len(human) != len(judge):
        raise ValueError(f"uzunluqlar fərqlidir: {len(human)} vs {len(judge)}")
    n = len(human)
    if n == 0:
        return 0.0
    po = agreement_rate(human, judge)
    label_list = list(labels)
    hc, jc = Counter(human), Counter(judge)
    pe = sum((hc.get(c, 0) / n) * (jc.get(c, 0) / n) for c in label_list)
    if abs(1.0 - pe) < 1e-12:
        # Hər iki tərəf eyni tək sinfi verib: uzlaşma məlumat daşımır.
        return 1.0 if po >= 1.0 - 1e-12 else 0.0
    return (po - pe) / (1.0 - pe)


def kappa_interpretation(kappa: float) -> str:
    if kappa < 0.20:
        return "zəif"
    if kappa < 0.41:
        return "orta zəif"
    if kappa < 0.61:
        return "orta"
    if kappa < 0.81:
        return "güclü"
    return "çox güclü"


def confusion_matrix(
    human: Sequence[str], judge: Sequence[str], labels: Iterable[str] = VERDICTS
) -> dict[str, dict[str, int]]:
    label_list = list(labels)
    matrix = {h: {j: 0 for j in label_list} for h in label_list}
    for h, j in zip(human, judge):
        matrix.setdefault(h, {j2: 0 for j2 in label_list}).setdefault(j, 0)
        matrix[h][j] += 1
    return matrix


def per_label_recall(
    human: Sequence[str], judge: Sequence[str], labels: Iterable[str] = VERDICTS
) -> dict[str, float]:
    """Hansı sinifdə judge zəifdir? Ümumi faiz bunu gizlədir."""
    out: dict[str, float] = {}
    for label in labels:
        idx = [i for i, h in enumerate(human) if h == label]
        out[label] = (
            sum(1 for i in idx if judge[i] == label) / len(idx) if idx else float("nan")
        )
    return out


# ------------------------------------------------------------------- yanlılıq
@dataclass
class BiasFinding:
    """Eyni məzmun, fərqli üslub → verdikt dəyişdimi?"""

    group: str
    styles: dict[str, str] = field(default_factory=dict)
    flipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"group": self.group, "styles": self.styles, "flipped": self.flipped}


def bias_probe(
    samples: Sequence[LabeledSample], verdicts: Sequence[str]
) -> dict[str, Any]:
    """Üslub yanlılığı: eyni (ssenari, insan etiketi) qrupunda verdikt sabitmi?

    Dəstdə hər qrup üçün qəsdən müxtəlif üslublu variantlar var (terse / verbose /
    confident / hedged / formatted / neutral). Məzmun və doğru qərar eynidir —
    yəni qrup daxilində verdikt DƏYİŞMƏMƏLİDİR. Dəyişirsə, bu judge-un
    verbosity / əminlik / format yanlılığıdır (FAILURE-TAXONOMY §10 Boşluq 7).

    Qeyd (dürüstlük üçün): mövqe (position) yanlılığı burada ölçülmür — bizim
    rubrika cüt müqayisə deyil, tək cavab qiymətləndirir, ona görə swap testi
    tətbiq olunmur. Dil yanlılığı isə ayrıca AZ/RU dəsti tələb edir.
    """
    groups: dict[str, list[int]] = {}
    for i, s in enumerate(samples):
        groups.setdefault(f"{s.scenario}/{s.label}", []).append(i)

    findings: list[BiasFinding] = []
    style_totals: Counter[str] = Counter()
    style_flips: Counter[str] = Counter()
    for group, idx in sorted(groups.items()):
        if len(idx) < 2 or len({samples[i].style for i in idx}) < 2:
            continue  # üslub müqayisəsi mümkün deyil
        styles = {samples[i].style: verdicts[i] for i in idx}
        majority = Counter(verdicts[i] for i in idx).most_common(1)[0][0]
        flipped = len(set(styles.values())) > 1
        findings.append(BiasFinding(group=group, styles=styles, flipped=flipped))
        for i in idx:
            style_totals[samples[i].style] += 1
            if verdicts[i] != majority:
                style_flips[samples[i].style] += 1

    n_groups = len(findings)
    n_flipped = sum(1 for f in findings if f.flipped)
    return {
        "n_groups": n_groups,
        "n_flipped": n_flipped,
        "style_flip_rate": (n_flipped / n_groups) if n_groups else 0.0,
        "by_style": {
            style: {
                "n": style_totals[style],
                "deviations": style_flips.get(style, 0),
                "rate": style_flips.get(style, 0) / style_totals[style],
            }
            for style in sorted(style_totals)
        },
        "findings": [f.to_dict() for f in findings if f.flipped],
        "not_measured": [
            "position bias — rubrika cüt müqayisə etmir, swap testi tətbiq olunmur",
            "dil yanlılığı — ayrıca AZ/RU etiketli dəst tələb edir",
        ],
    }


# --------------------------------------------------------------------- hesabat
@dataclass
class CalibrationReport:
    rubric_id: str
    rubric_version: str
    judge_model: str
    n: int
    agreement: float
    kappa: float
    labels_sha256: str
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    per_label_recall: dict[str, float] = field(default_factory=dict)
    label_counts: dict[str, int] = field(default_factory=dict)
    disagreements: list[dict[str, Any]] = field(default_factory=list)
    bias: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)
    dry_run: bool = False
    created_at: str = ""
    min_agreement: float = MIN_AGREEMENT
    min_kappa: float = MIN_KAPPA
    rule: str = CALIBRATION_RULE

    # -- qapı --------------------------------------------------------------
    @property
    def passed(self) -> bool:
        return (
            not self.dry_run
            and self.agreement >= self.min_agreement
            and self.kappa >= self.min_kappa
        )

    @property
    def blocking_reasons(self) -> list[str]:
        reasons: list[str] = []
        if self.dry_run:
            reasons.append(
                "DRY-RUN — real judge çağırışı olmayıb, bu rəqəmlər qiymətləndirmə "
                "üçün istifadə edilə BİLMƏZ"
            )
        if self.agreement < self.min_agreement:
            reasons.append(
                f"uyğunluq {self.agreement:.1%} < {self.min_agreement:.0%} — "
                f"RUBRİKA düzəlməlidir (dataset yox): {self.rule}"
            )
        if self.kappa < self.min_kappa:
            reasons.append(
                f"Cohen's kappa {self.kappa:.2f} < {self.min_kappa:.2f} "
                f"({kappa_interpretation(self.kappa)}) — xam faiz təsadüfi uyğunluğu gizlədir"
            )
        if self.errors:
            reasons.append(f"{len(self.errors)} nümunədə judge sxemi pozdu")
        return reasons

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["passed"] = self.passed
        d["kappa_interpretation"] = kappa_interpretation(self.kappa)
        d["blocking_reasons"] = self.blocking_reasons
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "CalibrationReport":
        known = {f for f in CalibrationReport.__dataclass_fields__}
        return CalibrationReport(**{k: v for k, v in d.items() if k in known})

    # -- insan üçün --------------------------------------------------------
    def summary_line(self) -> str:
        flag = "✅" if self.passed else "❌"
        return (
            f"{flag} judge kalibrasiyası · uyğunluq {self.agreement:.1%} "
            f"(hədd {self.min_agreement:.0%}) · κ={self.kappa:.2f} "
            f"({kappa_interpretation(self.kappa)}, hədd {self.min_kappa:.2f}) · "
            f"n={self.n} · {self.rubric_id}@{self.rubric_version} · {self.judge_model}"
            + (" · DRY-RUN" if self.dry_run else "")
        )

    def render_markdown(self) -> str:
        out = [
            "### Judge kalibrasiyası",
            "",
            self.summary_line(),
            "",
            f"Etiket dəsti: `{self.labels_sha256[:12]}` · sinif balansı: "
            + ", ".join(f"{k}={v}" for k, v in sorted(self.label_counts.items())),
            "",
        ]
        if self.blocking_reasons:
            out += ["**Bloklama:**", ""] + [f"- {r}" for r in self.blocking_reasons] + [""]
        out += ["| insan \\ judge | " + " | ".join(VERDICTS) + " |",
                "|---|" + "---|" * len(VERDICTS)]
        for h in VERDICTS:
            row = self.confusion.get(h, {})
            out.append(f"| {h} | " + " | ".join(str(row.get(j, 0)) for j in VERDICTS) + " |")
        out.append("")
        if self.bias:
            out += [
                f"Üslub yanlılığı: {self.bias.get('n_flipped', 0)}/"
                f"{self.bias.get('n_groups', 0)} qrupda verdikt üsluba görə dəyişdi "
                f"({self.bias.get('style_flip_rate', 0):.0%})",
                "",
            ]
        if self.disagreements:
            out += [f"<details><summary>Fikir ayrılığı ({len(self.disagreements)})</summary>", ""]
            for d in self.disagreements[:15]:
                out.append(
                    f"- `{d['id']}` insan **{d['human']}** / judge **{d['judge']}** "
                    f"(conf {d.get('confidence', 0):.2f}) — {d.get('judge_reason', '')}"
                )
            out += ["", "</details>", ""]
        return "\n".join(out)


# ----------------------------------------------------------------- yaddaş
def save_report(report: CalibrationReport, path: str | Path = DEFAULT_REPORT_PATH) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return p


def load_report(path: str | Path = DEFAULT_REPORT_PATH) -> CalibrationReport | None:
    p = Path(path)
    if not p.exists():
        return None
    return CalibrationReport.from_dict(json.loads(p.read_text(encoding="utf-8")))


# ----------------------------------------------------------------- kalibrasiya
def calibrate(
    client: JudgeClient,
    labels: CalibrationSet | str | Path = DEFAULT_LABELS_PATH,
    judge: RubricJudge | None = None,
    dry_run: bool = False,
    created_at: str = "",
) -> CalibrationReport:
    """Judge-i etiketli dəst üzərində qaçırır və uyğunluq + kappa hesablayır.

    Şəbəkəyə çıxmır — çıxışı `client` edir. Testlərdə mock klient verilir,
    ona görə bütün test dəsti API açarı olmadan qaçır.
    """
    dataset = labels if isinstance(labels, CalibrationSet) else load_labels(labels)
    judge = judge or RubricJudge()
    judge.bind(client)

    human: list[str] = []
    predicted: list[str] = []
    kept: list[LabeledSample] = []
    disagreements: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for sample in dataset.samples:
        try:
            decision, _meta = judge.decide(sample.to_case(), sample.answer)
        except JudgeProtocolError as exc:
            errors.append({"id": sample.id, "error": str(exc)})
            continue
        human.append(sample.label)
        predicted.append(decision.verdict)
        kept.append(sample)
        if decision.verdict != sample.label:
            disagreements.append(
                {
                    "id": sample.id,
                    "scenario": sample.scenario,
                    "style": sample.style,
                    "human": sample.label,
                    "judge": decision.verdict,
                    "confidence": decision.confidence,
                    "judge_reason": decision.reason,
                    "human_note": sample.note,
                }
            )

    return CalibrationReport(
        rubric_id=dataset.rubric,
        rubric_version=dataset.rubric_version,
        judge_model=getattr(client, "model", "?"),
        n=len(human),
        agreement=agreement_rate(human, predicted),
        kappa=cohens_kappa(human, predicted),
        labels_sha256=dataset.sha256,
        confusion=confusion_matrix(human, predicted),
        per_label_recall=per_label_recall(human, predicted),
        label_counts=dataset.label_counts,
        disagreements=disagreements,
        bias=bias_probe(kept, predicted),
        errors=errors,
        dry_run=dry_run,
        created_at=created_at,
    )


# ------------------------------------------------------- hesabata avtomatik düşmə
NO_CALIBRATION_WARNING = (
    "⚠️ JUDGE KALİBRASİYA EDİLMƏYİB — bu qaçışdakı judge nəticələri "
    "müdafiə olunmur (kalibrasiya edilməmiş judge nəticəsi elmi zibildir). "
    "Qaçır: `python evals/calibration/run_calibration.py`"
)


def judge_status(
    grader_names: Iterable[str], report_path: str | Path = DEFAULT_REPORT_PATH
) -> dict[str, Any]:
    """Qaçışda judge grader-i varsa, kalibrasiya vəziyyətini hesabat üçün qaytarır.

    Bu funksiya `report/normalize.py` və `report/pr_comment.py` tərəfindən
    çağırılır — yəni uyğunluq faizi və kappa hesabata AVTOMATIK düşür və
    ayrıca addım tələb etmədiyi üçün gizlədilə bilmir.
    """
    from agentproof.graders import registry  # dövri importdan qaçmaq üçün burada

    judged = sorted(
        {
            name
            for name in grader_names
            if name in registry.names() and registry.kind(name) == "judge"
        }
    )
    if not judged:
        return {"used": False}

    report = load_report(report_path)
    if report is None:
        return {"used": True, "graders": judged, "calibrated": False,
                "warning": NO_CALIBRATION_WARNING}
    return {
        "used": True,
        "graders": judged,
        "calibrated": True,
        "passed": report.passed,
        "agreement": report.agreement,
        "kappa": report.kappa,
        "kappa_interpretation": kappa_interpretation(report.kappa),
        "n": report.n,
        "rubric": f"{report.rubric_id}@{report.rubric_version}",
        "judge_model": report.judge_model,
        "dry_run": report.dry_run,
        "labels_sha256": report.labels_sha256,
        "blocking_reasons": report.blocking_reasons,
        "summary": report.summary_line(),
    }


# --------------------------------------------------------------- dry-run klienti
class ConstantJudgeClient:
    """Şəbəkəsiz "null model" — həmişə eyni verdikti verir.

    `--dry-run` rejimində boru xəttinin işlədiyini sübut edir VƏ eyni zamanda
    kappa-nın niyə lazım olduğunu göstərir: sabit verdikt xam faizdə hansısa
    rəqəm alır, amma kappa-sı ~0-dır. Bu klientin nəticəsi HEÇ VAXT
    qiymətləndirmə kimi istifadə olunmur — `dry_run=True` hesabatı bloklayır.
    """

    def __init__(self, verdict: str = "unjustified", model: str = "dry-run/constant") -> None:
        if verdict not in VERDICTS:
            raise ValueError(f"naməlum verdikt: {verdict!r}")
        self.verdict = verdict
        self.model = model
        self.calls = 0

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> JudgeRaw:
        self.calls += 1
        payload = {
            "verdict": self.verdict,
            "reason": "dry-run: sabit verdikt, məzmuna baxılmır",
            "confidence": 0.0,
        }
        return JudgeRaw(
            text=json.dumps(payload, ensure_ascii=False),
            meta={"model": self.model, "dry_run": True, "temperature_applied": False},
        )


class ScriptedJudgeClient:
    """Testlər üçün: nümunə id-sinə görə əvvəlcədən yazılmış cavab qaytarır.

    Prompt mətnində nümunənin cavabı olduğuna görə uyğunluq ona görə tapılır.
    Real API çağırışı YOXDUR.
    """

    def __init__(self, by_answer: dict[str, JudgeDecision | str], model: str = "mock/judge"):
        self.by_answer = by_answer
        self.model = model
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> JudgeRaw:
        self.calls.append((system, user))
        for needle, decision in self.by_answer.items():
            if needle and needle in user:
                if isinstance(decision, str):
                    decision = JudgeDecision(decision, "mock", 0.9)
                return JudgeRaw(
                    text=json.dumps(decision.to_dict(), ensure_ascii=False),
                    meta={"model": self.model, "temperature_applied": False},
                )
        raise AssertionError("ScriptedJudgeClient: uyğun nümunə tapılmadı")

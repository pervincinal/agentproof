"""LLM-as-judge qatı — YALNIZ subyektiv hallar üçün (STACK.md §8.3, grader-eng.md).

POZULMAZ QAYDA: bu modul `inspect_ai` import ETMİR (STACK.md §6).
İkinci qayda: determinist grader ilə ölçülə bilən heç nə buraya gəlmir. Judge
bahalıdır, qeyri-deterministdir və kalibrasiya tələb edir — `contains_all` ilə
həll olunan işi judge-a vermək məhsulun keyfiyyətini AŞAĞI salır.

Əsas istifadə halı `grading: requires_justification` (TRAPS.md §5):
korpusda "30 gün" həm doğru, həm səhv cavabdır — bayat standart pəncərə də 30,
canlı Aurora Plus üzv pəncərəsi də 30. Rəqəm eynidir; fərqi yalnız cavabın
ƏSASLANDIRMASI göstərir. Determinist grader bunu ayıra bilmir, ona görə burada.

Determinizm haqqında dürüst qeyd
-------------------------------
Messages API-də `seed` parametri YOXDUR — uydurmuruq. Determinizm üç yolla
təmin olunur və hər üçü `evidence`-də açıq yazılır:
  1. `temperature=0` — YALNIZ onu qəbul edən modellərdə. Opus 5 / Sonnet 5 /
     Fable 5 / Opus 4.7-4.8 sampling parametrlərini rədd edir (HTTP 400), ona
     görə həmin modellərdə sahə göndərilmir və `temperature_applied=False` qeyd
     olunur. Susmaq yerinə yazırıq: kalibrasiya rəqəmi bu fərqi gizlətməməlidir.
  2. Sabit prompt baytları — rubrika versiyalanır, prompt şablonu dəyişməzdir.
  3. `JudgeCache` — sorğunun sha256 barmaq izi ilə cavab keşi. Eyni giriş +
     eyni rubrika versiyası → bayt-bayt eyni verdikt. "Seed idarəsi"nin real
     qarşılığı budur.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from agentproof.graders.base import registry, require
from agentproof.types import AgentResponse, Case, GradeResult

# --------------------------------------------------------------------- verdikt
JUSTIFIED = "justified"
UNJUSTIFIED = "unjustified"
WRONG = "wrong"

VERDICTS: tuple[str, ...] = (JUSTIFIED, UNJUSTIFIED, WRONG)
"""Judge-in qərar dəsti. `passed` YALNIZ `justified` üçün doğrudur.

`unjustified` və `wrong` ayrı saxlanır, çünki audit hesabatında fərqli
hekayələrdir: birincisi "rəqəm düzdür, amma sübut yoxdur" (təsadüfi keçmiş
ola bilər), ikincisi "bayat bəndə istinad etdi" (nümayiş oluna bilən qüsur).
"""


# --------------------------------------------------------------------- rubrika
@dataclass(frozen=True)
class Rubric:
    """Versiyalanan rubrika. `version` GradeResult.evidence-də saxlanır.

    Rubrika mətnini dəyişmək = versiyanı qaldırmaq. Kalibrasiya rəqəmi
    həmişə KONKRET rubrika versiyasına aiddir — köhnə kalibrasiya yeni
    rubrikanı müdafiə etmir (bax `calibration.py`).
    """

    id: str
    version: str
    system: str
    template: str
    verdicts: tuple[str, ...] = VERDICTS

    def render(self, **fields: Any) -> str:
        return self.template.format(**fields)

    @property
    def schema(self) -> dict[str, Any]:
        """Struktur çıxış sxemi — {verdict, reason, confidence}.

        Qeyd: `confidence` üçün `minimum`/`maximum` GÖNDƏRİLMİR — Messages API
        `output_config.format.schema` içində `number` tipində bu açarları qəbul
        etmir (HTTP 400: "For 'number' type, properties maximum, minimum are not
        supported"). 0–1 aralığı `JudgeDecision.parse()` içində klemplənir və
        rubrika mətnində (qayda 6) tələb olunur.
        """
        return {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": list(self.verdicts)},
                "reason": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["verdict", "reason", "confidence"],
            "additionalProperties": False,
        }


REQUIRES_JUSTIFICATION_V1 = Rubric(
    id="requires_justification",
    version="v1",
    system=(
        "Sən audit qiymətləndiricisisən. Bir müştəri dəstək cavabının RƏQƏMİNİ deyil, "
        "həmin rəqəmə hansı YOLLA gəldiyini qiymətləndirirsən.\n"
        "\n"
        "Bu suallarda düzgün rəqəm eyni zamanda BAYAT (qüvvədən düşmüş) bənddə də görünür. "
        "Yəni rəqəm tək başına heç nə sübut etmir — fərqi yalnız əsaslandırma göstərir.\n"
        "\n"
        "Dəqiq bir qərar seç:\n"
        "  justified   — cavab İDARƏEDİCİ QAYDA-nı (adı, mahiyyəti və ya şərti ilə) "
        "göstərir VƏ rəqəmi ondan çıxarır.\n"
        "  unjustified — rəqəm düzgündür, amma heç bir idarəedici şərt göstərilmir: "
        "səbəbsiz rəqəm, ümumi \"siyasətimizə görə\", yalnız sualın təkrarı.\n"
        "  wrong       — cavab TƏLƏ QAYDALARINDAN birinə əsaslanır, bayat/ləğv edilmiş "
        "bəndə istinad edir, VƏ YA rəqəmin özü səhvdir.\n"
        "\n"
        "Qaydalar:\n"
        "  1. Yalnız YOL-a bax. Cavabın uzunluğu, tonu, əminliyi, formatı və nəzakəti "
        "qərara TƏSİR ETMİR. Uzun və səlis cavab qısa cavabdan üstün deyil.\n"
        "  2. İdarəedici qayda öz texniki adı ilə yazılmaya bilər — şərtin mahiyyəti "
        "(məs. \"Aurora Plus üzvü olduğunuz üçün\") kifayətdir.\n"
        "  3. Həm idarəedici, həm tələ qaydası adı çəkilibsə: cavab hansını ƏSAS "
        "götürürsə, qərar odur. Ayırd etmək mümkün deyilsə → unjustified.\n"
        "  4. Əmin deyilsənsə aşağı qərara en. `justified` vermək üçün əsaslandırma "
        "cavabda AÇIQ görünməlidir; güman etmək olmaz.\n"
        "  5. `reason` 25 sözdən qısa olsun və cavabdan qısa sitat gətirsin.\n"
        "  6. `confidence` sənin öz qərarına inamındır (0.0–1.0), cavabın əminliyi deyil."
    ),
    template=(
        "SUAL:\n{question}\n\n"
        "QİYMƏTLƏNDİRİLƏN CAVAB:\n{answer}\n\n"
        "KANONİK DÜZGÜN DƏYƏR: {answer_value}\n\n"
        "İDARƏEDİCİ QAYDA (cavab buna əsaslanmalıdır):\n{controlling_rule}\n\n"
        "TƏLƏ QAYDALARI (eyni və ya oxşar rəqəmi verən YANLIŞ yollar):\n{decoy_rules}"
    ),
)

RUBRICS: dict[str, Rubric] = {REQUIRES_JUSTIFICATION_V1.id: REQUIRES_JUSTIFICATION_V1}


def get_rubric(rubric_id: str) -> Rubric:
    if rubric_id not in RUBRICS:
        raise KeyError(f"naməlum rubrika: {rubric_id!r}; mövcud: {sorted(RUBRICS)}")
    return RUBRICS[rubric_id]


# ---------------------------------------------------------------------- model
_MODEL_TIER: dict[str, int] = {
    "claude-haiku-4-5": 1,
    "claude-sonnet-4-6": 2,
    "claude-sonnet-5": 3,
    "claude-opus-4-6": 3,
    "claude-opus-4-7": 4,
    "claude-opus-4-8": 4,
    "claude-opus-5": 5,
    "claude-fable-5": 6,
}

_SAMPLING_REJECTED: frozenset[str] = frozenset(
    {
        # Bu modellərdə `temperature` / `top_p` / `top_k` API-dən ÇIXARILIB —
        # göndərilsə HTTP 400 qaytarır. Susqun düşmək yerinə açıq qeyd edirik.
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-5",
        "claude-fable-5",
        "claude-mythos-5",
    }
)

DEFAULT_JUDGE_MODEL = "claude-opus-5"


def model_tier(model: str) -> int | None:
    return _MODEL_TIER.get(model)


def supports_temperature(model: str) -> bool:
    return model not in _SAMPLING_REJECTED


# --------------------------------------------------------------------- müqavilə
@dataclass(frozen=True)
class JudgeRaw:
    """Judge modelindən gələn xam cavab + sorğu metadatası."""

    text: str
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class JudgeClient(Protocol):
    """Judge modelinə tək çağırış. Testlərdə mock ilə əvəz olunur.

    Real API açarı olmadan bütün test dəsti qaçmalıdır — ona görə `RubricJudge`
    heç vaxt klienti özü yaratmır, konstruktorda alır.
    """

    model: str

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> JudgeRaw: ...


@dataclass(frozen=True)
class JudgeDecision:
    """Struktur çıxış: {verdict, reason, confidence}."""

    verdict: str
    reason: str
    confidence: float

    @staticmethod
    def parse(text: str, verdicts: tuple[str, ...] = VERDICTS) -> "JudgeDecision":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise JudgeProtocolError(f"judge JSON qaytarmadı: {text[:200]!r}") from exc
        if not isinstance(data, dict):
            raise JudgeProtocolError(f"judge obyekt qaytarmadı: {type(data).__name__}")
        missing = [k for k in ("verdict", "reason", "confidence") if k not in data]
        if missing:
            raise JudgeProtocolError(f"judge cavabında çatışmayan sahə(lər): {missing}")
        verdict = str(data["verdict"]).strip().lower()
        if verdict not in verdicts:
            raise JudgeProtocolError(
                f"naməlum verdikt {verdict!r}; icazəli: {list(verdicts)}"
            )
        try:
            confidence = float(data["confidence"])
        except (TypeError, ValueError) as exc:
            raise JudgeProtocolError(f"confidence ədəd deyil: {data['confidence']!r}") from exc
        return JudgeDecision(
            verdict=verdict,
            reason=str(data["reason"]).strip(),
            confidence=min(max(confidence, 0.0), 1.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "reason": self.reason, "confidence": self.confidence}


class JudgeProtocolError(ValueError):
    """Judge sxemə uyğun cavab vermədi — SƏSSİZCƏ keçmirik."""


# ----------------------------------------------------------------------- keş
class JudgeCache:
    """Sorğu barmaq izinə görə cavab keşi — determinizmin praktik təminatı.

    API-də `seed` yoxdur, ona görə təkrar qaçışda eyni nəticəni almağın yeganə
    dürüst yolu budur: eyni model + eyni rubrika versiyası + eyni prompt →
    diskdən eyni cavab. Keş faylları hesabat artefaktına daxil edilir ki, audit
    kənardan yenidən yoxlana bilsin.
    """

    def __init__(self, directory: str | os.PathLike[str] | None) -> None:
        self.dir = Path(directory) if directory else None

    @staticmethod
    def fingerprint(model: str, system: str, user: str) -> str:
        payload = json.dumps([model, system, user], ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> JudgeRaw | None:
        if self.dir is None:
            return None
        path = self.dir / f"{key}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return JudgeRaw(text=data["text"], meta=dict(data.get("meta", {}), cache_hit=True))

    def put(self, key: str, raw: JudgeRaw) -> None:
        if self.dir is None:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f"{key}.json").write_text(
            json.dumps({"text": raw.text, "meta": raw.meta}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# -------------------------------------------------------------- real API klienti
class AnthropicJudgeClient:
    """Rəsmi Anthropic SDK üzərindən judge çağırışı.

    `anthropic` paketi YALNIZ burada və YALNIZ ilk çağırışda import olunur —
    beləliklə `agentproof.graders` paketi SDK quraşdırılmadan da qalxır və
    bütün testlər mock ilə, açarsız qaçır.
    """

    def __init__(
        self,
        model: str = DEFAULT_JUDGE_MODEL,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        client: Any = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is None:
            import anthropic  # lazy: modul səviyyəsində olsa testlər SDK tələb edərdi

            self._client = anthropic.Anthropic()
        return self._client

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> JudgeRaw:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
        # Opus 5 / Sonnet 5 / Fable 5 / Opus 4.7-4.8 sampling parametrlərini
        # rədd edir (400). Göndərmirik və bunu GİZLƏTMİRİK — meta-ya yazırıq.
        applied = supports_temperature(self.model)
        if applied:
            kwargs["temperature"] = self.temperature
        response = self._ensure_client().messages.create(**kwargs)
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
        usage = getattr(response, "usage", None)
        return JudgeRaw(
            text=text,
            meta={
                "model": self.model,
                "temperature_applied": applied,
                "temperature": self.temperature if applied else None,
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            },
        )


# ------------------------------------------------------------------- konfiqurasiya
@dataclass
class JudgeConfig:
    """Judge konfiqurasiyası.

    `sut_model` verilibsə, judge-un ondan GÜCLÜ olduğu yoxlanılır: zəif judge
    güclü sistemi qiymətləndirəndə self-preference və qabiliyyət tavanı
    yanlılığı hesabatı yararsız edir (FAILURE-TAXONOMY §10 Boşluq 7).
    """

    model: str = DEFAULT_JUDGE_MODEL
    rubric_id: str = "requires_justification"
    temperature: float = 0.0
    max_tokens: int = 1024
    cache_dir: str | None = None
    sut_model: str | None = None
    min_confidence: float = 0.0
    """Bundan aşağı inamlı verdikt `skipped` sayılır (0.0 = filtr yoxdur)."""

    def validate(self) -> None:
        if self.temperature != 0.0:
            raise ValueError(
                "judge temperature 0 olmalıdır — qeyri-determinist judge kalibrasiya "
                f"rəqəmini yararsız edir (verilən: {self.temperature})"
            )
        get_rubric(self.rubric_id)
        if self.sut_model is None:
            return
        judge_tier, sut_tier = model_tier(self.model), model_tier(self.sut_model)
        if judge_tier is None or sut_tier is None:
            return  # naməlum model — `evidence`-də xəbərdarlıq kimi görünür
        if judge_tier <= sut_tier:
            raise ValueError(
                f"judge modeli ({self.model}, tier {judge_tier}) qiymətləndirdiyi "
                f"sistemdən ({self.sut_model}, tier {sut_tier}) güclü deyil — "
                "bu konfiqurasiyada nəticə müdafiə olunmur"
            )


# ----------------------------------------------------------------------- grader
class RubricJudge:
    """`requires_justification` grader-i (STACK.md §8.3 `RubricJudge`).

    expect:
      answer_value: str       — kanonik düzgün dəyər (məs. "30 gün")   [məcburi]
      controlling_rule: str   — cavabın əsaslanmalı olduğu qayda        [məcburi]
      decoy_rules: [str]      — eyni rəqəmi verən yanlış yollar         [tövsiyə]
      rubric: str             — rubrika id (default requires_justification)

    Qeyd: `kind = "judge"` olduğuna görə bu grader `--stage judge` mərhələsinə
    düşür və hər PR-da qaçmır (STACK.md §8.6, 6 dəqiqə qaydası).
    """

    name = "requires_justification"
    kind = "judge"

    def __init__(self, client: JudgeClient | None = None, config: JudgeConfig | None = None):
        self.config = config or JudgeConfig()
        self.config.validate()
        self.client = client
        self.cache = JudgeCache(self.config.cache_dir)

    # -- konfiqurasiya -----------------------------------------------------
    def bind(self, client: JudgeClient, config: JudgeConfig | None = None) -> "RubricJudge":
        """Registry-dəki singleton-a klient bağlayır (qaçışdan əvvəl, run.py-dan)."""
        self.client = client
        if config is not None:
            config.validate()
            self.config = config
            self.cache = JudgeCache(config.cache_dir)
        return self

    # -- əsas iş -----------------------------------------------------------
    def build_prompt(self, case: Case, answer: str) -> tuple[Rubric, str, str]:
        rubric = get_rubric(str(case.expect.get("rubric", self.config.rubric_id)))
        decoys = [str(d) for d in case.expect.get("decoy_rules", [])]
        user = rubric.render(
            question=case.query,
            answer=answer.strip() or "(boş cavab)",
            answer_value=str(require(case, "answer_value", self.name)),
            controlling_rule=str(require(case, "controlling_rule", self.name)),
            decoy_rules="\n".join(f"- {d}" for d in decoys) or "- (verilməyib)",
        )
        return rubric, rubric.system, user

    def decide(self, case: Case, answer: str) -> tuple[JudgeDecision, dict[str, Any]]:
        """Prompt qur → klienti çağır (keşlə) → struktur cavabı parse et."""
        if self.client is None:
            raise RuntimeError(
                "judge klienti bağlanmayıb — `RubricJudge.bind(client)` çağırın "
                "(testlərdə mock, qaçışda AnthropicJudgeClient)"
            )
        rubric, system, user = self.build_prompt(case, answer)
        key = JudgeCache.fingerprint(self.client.model, system, user)
        raw = self.cache.get(key)
        if raw is None:
            raw = self.client.complete(system, user, rubric.schema)
            self.cache.put(key, raw)
        decision = JudgeDecision.parse(raw.text, rubric.verdicts)
        meta = {
            "rubric_id": rubric.id,
            "rubric_version": rubric.version,
            "judge_model": self.client.model,
            "prompt_sha256": key,
            **raw.meta,
        }
        return decision, meta

    def grade(self, case: Case, response: AgentResponse) -> GradeResult:
        try:
            decision, meta = self.decide(case, response.text)
        except JudgeProtocolError as exc:
            # Judge sxemi pozdu: bu case-in NƏTİCƏSİ yoxdur, uğursuzluğu deyil.
            return GradeResult.skip(self.name, f"judge cavabı yararsız: {exc}", {"error": str(exc)})

        if decision.confidence < self.config.min_confidence:
            return GradeResult.skip(
                self.name,
                f"judge inamı həddin altındadır ({decision.confidence:.2f} < "
                f"{self.config.min_confidence:.2f}) — nəticə metrikaya daxil edilmir",
                {**meta, **decision.to_dict()},
            )

        passed = decision.verdict == JUSTIFIED
        reason = {
            JUSTIFIED: f"əsaslandırma idarəedici qaydanı göstərir — {decision.reason}",
            UNJUSTIFIED: (
                "rəqəm düzgündür, amma idarəedici şərt göstərilmir — bu rəqəm bayat "
                f"bənddən də gələ bilərdi ({decision.reason})"
            ),
            WRONG: f"cavab yanlış qaydaya/bayat bəndə əsaslanır — {decision.reason}",
        }[decision.verdict]
        return GradeResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            grader=self.name,
            reason=reason,
            evidence={
                **meta,
                **decision.to_dict(),
                "answer_value": case.expect.get("answer_value"),
                "controlling_rule": case.expect.get("controlling_rule"),
                "decoy_rules": case.expect.get("decoy_rules", []),
                "answer_excerpt": response.text[:400],
            },
        )


# Registry-yə tək singleton kimi düşür; klient qaçışdan əvvəl `bind()` ilə verilir.
registry.add(RubricJudge())

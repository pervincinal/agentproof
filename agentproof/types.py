"""Sistem boyu sabit tiplər (STACK.md §8.1).

Bu modul heç nə import etmir — nə `inspect_ai`, nə httpx. Bütün digər qatlar
bundan asılıdır, bu heç nədən asılı deyil.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

GraderKind = Literal["deterministic", "judge"]

#: Oxuna bilməyən konfiqurasiya dəyəri üçün AÇIQ sentinel.
#:
#: Boş sətir və ya ağlabatan default YAZILMIR: "" hesabatda "sahə boşdur"
#: kimi görünür və oxucu onu susqun keçir; `"unknown"` isə iddia edir —
#: "bu dəyər ölçülmədi". LIM-E06-nın bütün mahiyyəti budur.
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Case:
    """Dataset jsonl-in bir sətri."""

    id: str
    input: str | list[dict[str, str]]
    grader: str
    tags: list[str] = field(default_factory=list)
    expect: dict[str, Any] = field(default_factory=dict)
    severity: Literal["low", "medium", "high"] = "medium"
    source: str = ""
    repeat: int | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Case":
        return Case(
            id=str(d["id"]),
            input=d["input"],
            grader=d["grader"],
            tags=list(d.get("tags", [])),
            expect=dict(d.get("expect", {})),
            severity=d.get("severity", "medium"),
            source=d.get("source", ""),
            repeat=d.get("repeat"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "input": self.input,
            "grader": self.grader,
            "tags": self.tags,
            "expect": self.expect,
            "severity": self.severity,
            "source": self.source,
            "repeat": self.repeat,
        }

    @property
    def query(self) -> str:
        """Son istifadəçi növbəsi (çoxnövbəli case-lərdə sonuncu user mesajı)."""
        if isinstance(self.input, str):
            return self.input
        for msg in reversed(self.input):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""


@dataclass
class AgentRequest:
    messages: list[dict[str, str]]
    session_id: str
    seed: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_case(case: Case, session_id: str, seed: int | None = None) -> "AgentRequest":
        if isinstance(case.input, str):
            messages = [{"role": "user", "content": case.input}]
        else:
            messages = [dict(m) for m in case.input]
        return AgentRequest(
            messages=messages,
            session_id=session_id,
            seed=seed,
            metadata={"case_id": case.id},
        )

    @property
    def query(self) -> str:
        for msg in reversed(self.messages):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "model": self.model,
        }

    @staticmethod
    def from_dict(d: dict[str, Any] | None) -> "Usage | None":
        if not d:
            return None
        return Usage(
            input_tokens=int(d.get("input_tokens", 0)),
            output_tokens=int(d.get("output_tokens", 0)),
            cached_tokens=int(d.get("cached_tokens", 0)),
            model=d.get("model", ""),
        )


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "result": self.result,
            "error": self.error,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "ToolCall":
        return ToolCall(
            name=d.get("name", ""),
            arguments=dict(d.get("arguments", {})),
            result=d.get("result"),
            error=d.get("error"),
        )


@dataclass
class RetrievedChunk:
    """Retrieval grader-ləri üçün məcburi sahə."""

    chunk_id: str
    text: str = ""
    score: float | None = None
    document: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "score": self.score,
            "document": self.document,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "RetrievedChunk":
        return RetrievedChunk(
            chunk_id=str(d.get("chunk_id", "")),
            text=d.get("text", ""),
            score=d.get("score"),
            document=d.get("document", ""),
        )


@dataclass
class AgentResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    retrieved: list[RetrievedChunk] = field(default_factory=list)
    usage: Usage | None = None
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    """Hədəf sistemin infrastruktur xətası (rate limit, provider yoxdur, ...).

    Bu None deyilsə, cavab MƏZMUN uğursuzluğu kimi sayılmamalıdır —
    `SETUP.md §7.2`-də sadalanan Dify xəta kodları burada saxlanır.
    """

    error_class: str | None = None
    """Xətanın SƏBƏB SİNFİ (`agentproof/failure.py`): `rate_limit` ·
    `credit_exhausted` · `auth` · `bad_request` · `unknown`.

    `error` NƏ baş verdiyini deyir (hədəfin öz kodu), bu sahə isə NƏ ETMƏLİ
    olduğunu: `rate_limit` gözləməklə keçir, `credit_exhausted` keçmir. AP-024-ə
    qədər hər ikisi eyni `completion_request_error` kodu altında idi və qaçışa
    baxan adam gözləməklə balans doldurmaq arasında qərar verə bilmirdi.

    Köhnə artefaktlarda YOXDUR (`None`) — `failure.reason_for_response()` onu
    xam `dify_error`-dan yenidən hesablayır.
    """

    attempts: int = 1
    """Bu cavab üçün hədəfə NEÇƏ HTTP sorğusu getdi (backoff təkrarları daxil).

    `1`-dən böyükdürsə, aradakı cəhdlər atılıb — amma tokenləri yanıb
    (`retry_usage`). AP-026: yanan token hesabatdan itməməlidir.
    """

    retry_usage: "Usage | None" = None
    """Backoff zamanı ATILMIŞ cəhdlərin token istifadəsi (varsa).

    Bu tokenlər uğurlu cavaba daxil deyil, amma pulu ödənilib. `usage`-a
    qatılmır (o, ölçmənin özüdür), ayrıca `wasted_cost_usd`-ə gedir.
    """

    turns: list["AgentResponse"] = field(default_factory=list)
    """Çoxnövbəli case-də HƏR NÖVBƏNİN öz cavabı (tək növbədə boş qalır).

    Kontekst itkisi (C1) məhz növbələr ARASINDA görünür: agent 2-ci növbədə
    sifariş nömrəsini unudursa, bu, yalnız növbə-növbə baxanda bilinir. Ona görə
    yekun cavabla yanaşı hər növbənin mətni, tool çağırışları, `usage`-ı və
    retrieval-ı ayrıca saxlanılır.

    Yuxarıdakı sahələrin çoxnövbəli semantikası (`adapters/http_agent.py`):
      text        -> SONUNCU növbənin mətni (qiymətləndirilən yekun cavab)
      tool_calls  -> BÜTÜN növbələrin birləşməsi, sıra ilə. `forbidden_tools`
                     üçün başqa cür olmaz: 2-ci növbədəki qadağan olunmuş
                     çağırış son növbəyə baxmaqla görünməz.
      retrieved   -> bütün növbələrin birləşməsi, `chunk_id` üzrə təkrarsız
      usage       -> növbələrin CƏMİ (xərc bütöv söhbətə görə hesablanır)
      latency_ms  -> növbələrin cəmi
    """

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "tool_calls": [t.to_dict() for t in self.tool_calls],
            "retrieved": [r.to_dict() for r in self.retrieved],
            "usage": self.usage.to_dict() if self.usage else None,
            "latency_ms": self.latency_ms,
            "raw": self.raw,
            "error": self.error,
            "error_class": self.error_class,
            "attempts": self.attempts,
            "retry_usage": self.retry_usage.to_dict() if self.retry_usage else None,
            "turns": [t.to_dict() for t in self.turns],
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "AgentResponse":
        return AgentResponse(
            text=d.get("text", ""),
            tool_calls=[ToolCall.from_dict(t) for t in d.get("tool_calls", [])],
            retrieved=[RetrievedChunk.from_dict(r) for r in d.get("retrieved", [])],
            usage=Usage.from_dict(d.get("usage")),
            latency_ms=int(d.get("latency_ms", 0)),
            raw=d.get("raw", {}),
            error=d.get("error"),
            # Köhnə artefaktda (`schema_version` 1/2) bu üç sahə YOXDUR —
            # default-lar köhnə davranışın eynisidir, oxuma sınmır.
            error_class=d.get("error_class"),
            # `0` HƏQİQİ dəyərdir: "sorğu ümumiyyətlə göndərilmədi" (qaçış
            # dayandırılıb). `or 1` yazmaq onu 1-ə çevirib ölçülməyən cəhd
            # kimi saydırardı — yəni olmayan xərci naməlum göstərərdi.
            attempts=1 if d.get("attempts") is None else int(d["attempts"]),
            retry_usage=Usage.from_dict(d.get("retry_usage")),
            turns=[AgentResponse.from_dict(t) for t in d.get("turns", [])],
        )

    @property
    def n_turns(self) -> int:
        """Neçə növbə göndərildi (tək növbəli cavabda 1)."""
        return len(self.turns) or 1

    @property
    def turn_texts(self) -> list[str]:
        """Növbə-növbə cavab mətnləri — kontekst itkisini burada axtarın."""
        return [t.text for t in self.turns] or [self.text]


@dataclass
class GradeResult:
    passed: bool
    score: float
    grader: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False
    """Grader bu case üçün qərar verə bilmədi (məs. `usage` yoxdur).

    Səssiz keçmə DEYİL: hesabatda ayrıca sayılır, metrikaya daxil olmur.
    `skipped=True` olanda `passed` mənasızdır — əvvəlcə bunu yoxla.
    """

    def __post_init__(self) -> None:
        if not self.passed and not self.skipped and not self.reason:
            raise ValueError(
                f"grader '{self.grader}': passed=False üçün boş reason qəbul olunmur "
                "(STACK.md §8.3 müqavilə şərti)"
            )

    @staticmethod
    def skip(grader: str, reason: str, evidence: dict[str, Any] | None = None) -> "GradeResult":
        return GradeResult(
            passed=False,
            score=0.0,
            grader=grader,
            reason=reason,
            evidence=evidence or {},
            skipped=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "grader": self.grader,
            "reason": self.reason,
            "evidence": self.evidence,
            "skipped": self.skipped,
        }


@dataclass
class CaseResult:
    case_id: str
    response: AgentResponse
    grade: GradeResult
    cost_usd: float | None = None
    """UĞURLU cəhdlərin xərci. `None` = ölçülmədi (usage gəlmədi), sıfır DEYİL."""

    latency_ms: int = 0
    attempt: int = 1
    tags: list[str] = field(default_factory=list)
    severity: str = "medium"

    wasted_cost_usd: float = 0.0
    """UĞURSUZ cəhdlərə gedən ÖLÇÜLƏN xərc (AP-026).

    Sınan sorğu da token yandırır. `full-run-03`-də 75 sorğu sındı və hamısının
    `cost_usd`-i `null` idi — yəni qeydlər $23.72 göstərdi, hesabdan ~$40 getdi.
    """

    unmeasured_attempts: int = 0
    """Sınan, amma `usage` QAYTARMAYAN cəhdlərin sayı.

    Bunların xərci NAMƏLUMDUR — sıfır deyil. `wasted_cost_usd`-ə qatılmır,
    çünki qatılsa ölçülməmiş şey ölçülmüş kimi görünərdi; ayrıca sayılır ki,
    "audit nəyə başa gəlir" sualına verilən cavabın hansı hissəsinin ölçüldüyü
    bilinsin.
    """

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "response": self.response.to_dict(),
            "grade": self.grade.to_dict(),
            "cost_usd": self.cost_usd,
            "wasted_cost_usd": self.wasted_cost_usd,
            "unmeasured_attempts": self.unmeasured_attempts,
            "latency_ms": self.latency_ms,
            "attempt": self.attempt,
            "tags": self.tags,
            "severity": self.severity,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "CaseResult":
        g = d["grade"]
        return CaseResult(
            case_id=d["case_id"],
            response=AgentResponse.from_dict(d.get("response", {})),
            grade=GradeResult(
                passed=g["passed"],
                score=g["score"],
                grader=g["grader"],
                reason=g.get("reason", ""),
                evidence=g.get("evidence", {}),
                skipped=g.get("skipped", False),
            ),
            cost_usd=d.get("cost_usd"),
            # Köhnə artefaktda yoxdur: 0.0 / 0 = "bu qaçışda ölçülməyib" —
            # `totals["cost_coverage"]["status"]` onu ayrıca göstərir.
            wasted_cost_usd=float(d.get("wasted_cost_usd", 0.0) or 0.0),
            unmeasured_attempts=int(d.get("unmeasured_attempts", 0) or 0),
            latency_ms=int(d.get("latency_ms", 0)),
            attempt=int(d.get("attempt", 1)),
            tags=list(d.get("tags", [])),
            severity=d.get("severity", "medium"),
        )


#: 1 -> 2: retrieval konfiqurasiyası (`embedding_model`, `embedding_provider`,
#: `effective_top_k`, `reranking_enabled`) artefaktın öz içindədir. `1`
#: oxunmağa davam edir — həmin sahələr `UNKNOWN` / `None` qalır.
#:
#: 2 -> 3 (AP-024 / AP-026): xəta SƏBƏB SİNFİ (`response.error_class`,
#: `totals["skipped_by_reason"]`) və xərcin uğurlu/yandırılan/ölçülməyən
#: bölgüsü (`wasted_cost_usd`, `unmeasured_attempts`, `totals["cost_coverage"]`).
#: `1` və `2` oxunmağa DAVAM EDİR: yeni sahələr default alır və
#: `cost_coverage.status` onların ölçülmədiyini açıq göstərir.
SCHEMA_VERSION = 3


def _opt_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_bool(value: Any) -> bool | None:
    return bool(value) if isinstance(value, bool) else None


@dataclass
class RunRecord:
    """Bizim sabit sxemimiz — Inspect-in log formatından asılı deyil (R2)."""

    run_id: str
    target: str
    target_version: str
    model: str
    dataset_hash: str
    started_at: str
    results: list[CaseResult] = field(default_factory=list)
    totals: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    # --- retrieval konfiqurasiyası (LIM-E06 / AP-019) ---------------------
    # Bu dörd sahə olmadan qaçış artefaktı öz-özünü təsvir etmir: embedder və
    # `top_k` hesabatın ən yük daşıyan parametrləridir, amma kənar sənəddən
    # oxunurdu. VALID-03-də DSL `4`, faktiki dəyər `8` idi — fərqi yalnız
    # canlı sistemə sorğu ataraq tapmaq mümkün oldu.
    #
    # Dəyərlər CANLI sistemdən gəlir (`runner/retrieval_config.py` ->
    # `GET /v1/datasets/{id}`), sənəddən yox. Oxuna bilməyəndə `UNKNOWN` /
    # `None` qalır və `totals["retrieval_check"]` səbəbi göstərir.
    embedding_model: str = UNKNOWN
    embedding_provider: str = UNKNOWN
    effective_top_k: int | None = None
    reranking_enabled: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "target": self.target,
            "target_version": self.target_version,
            "model": self.model,
            "dataset_hash": self.dataset_hash,
            "started_at": self.started_at,
            "embedding_model": self.embedding_model,
            "embedding_provider": self.embedding_provider,
            "effective_top_k": self.effective_top_k,
            "reranking_enabled": self.reranking_enabled,
            "results": [r.to_dict() for r in self.results],
            "totals": self.totals,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "RunRecord":
        return RunRecord(
            run_id=d["run_id"],
            target=d["target"],
            target_version=d.get("target_version", ""),
            model=d.get("model", ""),
            dataset_hash=d.get("dataset_hash", ""),
            started_at=d.get("started_at", ""),
            results=[CaseResult.from_dict(r) for r in d.get("results", [])],
            totals=d.get("totals", {}),
            schema_version=int(d.get("schema_version", 1)),
            # Köhnə (schema_version 1) artefaktda bu sahələr YOXDUR. Onları
            # ağlabatan dəyərlə doldurmaq, ölçülməmiş konfiqurasiyanı ölçülmüş
            # kimi göstərmək olardı — ona görə açıq `UNKNOWN` / `None`.
            embedding_model=str(d.get("embedding_model") or UNKNOWN),
            embedding_provider=str(d.get("embedding_provider") or UNKNOWN),
            effective_top_k=_opt_int(d.get("effective_top_k")),
            reranking_enabled=_opt_bool(d.get("reranking_enabled")),
        )


@dataclass
class RunDelta:
    fixed: list[str] = field(default_factory=list)
    broken: list[str] = field(default_factory=list)
    still_failing: list[str] = field(default_factory=list)
    flaky: list[str] = field(default_factory=list)
    new_cases: list[str] = field(default_factory=list)
    removed_cases: list[str] = field(default_factory=list)
    pass_rate_before: float = 0.0
    pass_rate_after: float = 0.0
    cost_delta: float = 0.0
    p50_delta_ms: float = 0.0
    p95_delta_ms: float = 0.0
    broken_high_severity: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixed": self.fixed,
            "broken": self.broken,
            "still_failing": self.still_failing,
            "flaky": self.flaky,
            "new_cases": self.new_cases,
            "removed_cases": self.removed_cases,
            "pass_rate_before": self.pass_rate_before,
            "pass_rate_after": self.pass_rate_after,
            "cost_delta": self.cost_delta,
            "p50_delta_ms": self.p50_delta_ms,
            "p95_delta_ms": self.p95_delta_ms,
            "broken_high_severity": self.broken_high_severity,
        }

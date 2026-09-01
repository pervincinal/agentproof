"""Preflight — hədəfin NƏYİ ölçüləbilir etdiyini auditdən ƏVVƏL göstərir (AP-032).

    python -m agentproof.preflight --target dify_http

Satış zəngindən sonrakı ilk texniki sual "sizin sisteminizi ölçə bilərikmi?"
olur. Müqavilədəki `health()` yalnız `bool` qaytarır: "canlıdır". Əsl sual isə
başqadır — **nəyi ölçə bilərik**. Hədəf `retrieved[]` vermirsə bütün retrieval
grader-ləri, `tool_calls` vermirsə tool grader-i, `usage` vermirsə xərc
grader-i SIRADAN ÇIXIR. İndiyə qədər bu yalnız tam qaçış qurulandan sonra —
yəni bir neçə günlük işdən sonra — bilinirdi.

Preflight həmin cavabı 3 sorğu ilə verir və çıxışı birbaşa müştəri sənədinə
köçürülə bilən formadadır: *"sizin sistemdə bu 3 ölçü mümkün deyil, çünki API
bunları qaytarmır"*.

ZONDLAR
-------
    1. health        adapter hədəfə çata bilirmi
    2. answer        tək növbəli sorğuya MƏTN qayıdırmı
    3. tool_calls    icra olunan tool-lar görünürmü          } eyni cavabdan
    4. retrieved     bilik bazası parçaları görünürmü        } oxunur —
    5. usage         token hesabı görünürmü                  } əlavə sorğu YOX
    6. cost          `cost_under` HƏQİQƏTƏN qərar verə bilirmi
    7. multi_turn    söhbət zəncirlənirmi (kontekst qalırmı)

2-6 BİR sorğudan oxunur: hər ölçü üçün ayrıca sorğu göndərmək müştərinin
pulunu heç bir əlavə məlumat vermədən yandırardı.

5-ci və 6-cı zond QƏSDƏN ayrıdır. Canlı Dify-da `usage` GƏLİR, amma model adı
gəlmir — `cost_under` isə qiymət cədvəlində model tapmayanda `skipped` verir.
Yəni "token görünür" ilə "xərc ölçülür" EYNİ ŞEY DEYİL. Ona görə xərc zondu
sahəyə deyil, GRADER-in öz qərarına baxır: yeganə etibarlı sübut budur.

"YOX" NƏ DEMƏKDİR
-----------------
Hər "yox" üçün hansı grader ailəsinin sıradan çıxdığı ADI ilə yazılır
(`FIELD_GRADERS`). Bu siyahı `test_preflight.py`-də registry ilə tutuşdurulur:
yeni grader əlavə olunanda o, hansısa sahəyə bağlanmalıdır — əks halda
preflight sabah "hər şey ölçülür" deyib bir ailəni unudardı.

ÖLÇÜLMƏYƏNİ "SIFIR" YAZMIRIQ
----------------------------
Zond özü sınarsa (xəta, timeout) nəticə `error`-dur, `no` DEYİL: "hədəf bu
sahəni vermir" ilə "biz ölçə bilmədik" fərqli iddialardır və hesabatda
qarışsalar, müştəriyə olmayan bir məhdudiyyət danışılardı.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from agentproof.adapters import create_adapter
from agentproof.adapters.env_config import adapter_config_from_env
from agentproof.types import UNKNOWN, AgentRequest, AgentResponse

# ============================================================== zond nəticələri
YES = "yes"
NO = "no"
ERROR = "error"
SKIPPED = "skipped"

#: Zondun cavabı `no` OLA BİLMƏZ — ölçmənin özü alınmadı.
UNMEASURED = (ERROR, SKIPPED)


# ================================================= sahə -> grader ailəsi
#: Hansı grader HANSI cavab sahəsindən asılıdır. `test_preflight.py` bunu
#: registry ilə tutuşdurur: bağlanmamış grader qalsa test SINIR.
FIELD_GRADERS: dict[str, tuple[str, ...]] = {
    "text": (
        "consistency_at_k",
        "contains_all",
        "contains_none",
        "json_schema",
        "no_leak",
        "regex_match",
        "requires_justification",
    ),
    "tool_calls": ("tool_call_matches",),
    "retrieved": ("precision_at_k", "retrieval_hit_at_k"),
    # `usage` sahəsi DEYİL, XƏRCİN HESABLANA BİLMƏSİ — token gəlib model
    # etiketi gəlmirsə sahə var, grader yenə də `skipped` verir.
    "cost": ("cost_under",),
    "latency_ms": ("latency_under",),
}

#: Zondun adı -> həmin zond sınanda ölçülməz qalan sahə. `usage` zondu burada
#: YOXDUR: o, xam sahəni göstərən MƏLUMAT sətridir, qərarı `cost` verir.
PROBE_FIELD = {
    "answer": "text",
    "tool_calls": "tool_calls",
    "retrieved": "retrieved",
    "cost": "cost",
}


# =================================================================== zondlar
#: Tək sorğu ilə HƏM bilik bazasına, HƏM tool-a toxunmağa çalışan sual.
#: İkisini ayrı-ayrı soruşmaq iki sorğu deməkdir — eyni məlumat, iki qat pul.
DEFAULT_PROBE = (
    "What is the restocking fee for an opened item, "
    "and can you look up the status of order ORD-10001?"
)
#: Çoxnövbəli zond: nişan İLK növbədədir, sual SONUNCUda. Cavab nişanı yalnız
#: söhbət zəncirlənibsə bilə bilər.
DEFAULT_MEMO = "ORD-10001"
DEFAULT_FOLLOW_UP = ("My order number is {memo}. What is your standard return window?",
                     "Thanks. Which order number did I just give you?")


@dataclass
class ProbeResult:
    key: str
    title: str
    status: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def graders_lost(self) -> tuple[str, ...]:
        """Bu zond `no` verəndə sıradan çıxan grader ailəsi."""
        if self.status != NO:
            return ()
        return FIELD_GRADERS.get(PROBE_FIELD.get(self.key, ""), ())

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe": self.key,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "graders_lost": list(self.graders_lost),
            "evidence": self.evidence,
        }


@dataclass
class PreflightReport:
    target: str
    target_version: str
    probes: list[ProbeResult] = field(default_factory=list)
    latencies_ms: list[int] = field(default_factory=list)
    tokens: dict[str, int] = field(default_factory=dict)
    requests_sent: int = 0

    # ---- nəticələr ---------------------------------------------------
    def by_key(self, key: str) -> ProbeResult | None:
        return next((p for p in self.probes if p.key == key), None)

    @property
    def field_status(self) -> dict[str, str]:
        """Hər ölçmə sahəsi: `yes` (gəldi) · `no` (gəlmədi) · ölçülmədi.

        Üç vəziyyət QƏSDƏN üçdür. İkiyə endirsək — "gəldi / gəlmədi" —
        cavabı ümumiyyətlə ala bilmədiyimiz hal "hədəf bu sahəni vermir"
        kimi oxunardı və müştəriyə OLMAYAN bir məhdudiyyət danışardıq.
        """
        status = {
            f: (probe.status if (probe := self.by_key(key)) else SKIPPED)
            for key, f in PROBE_FIELD.items()
        }
        # `latency_ms`-i ayrıca zond ölçmür: gecikmə hər cavabla gəlir. AMMA
        # cavabın ÖZÜ alınmadısa "gecikmə ölçülür" iddiası boşdur — nəqliyyat
        # xətasının 12 ms-i hədəfin gecikmə profili deyil.
        answer = self.by_key("answer")
        status["latency_ms"] = (
            YES if self.latencies_ms and answer is not None and answer.status == YES
            else SKIPPED
        )
        return status

    def _graders_where(self, *statuses: str) -> tuple[str, ...]:
        names: set[str] = set()
        for field_name, status in self.field_status.items():
            if status in statuses:
                names.update(FIELD_GRADERS.get(field_name, ()))
        return tuple(sorted(names))

    @property
    def graders_lost(self) -> tuple[str, ...]:
        """Hədəf sahəni VERMİR — bu grader-lər həmişə `skipped` olacaq."""
        return self._graders_where(NO)

    @property
    def graders_available(self) -> tuple[str, ...]:
        return self._graders_where(YES)

    @property
    def graders_unverified(self) -> tuple[str, ...]:
        """Zond nəticə vermədi — grader işləyə DƏ bilər, bilmirik."""
        return self._graders_where(*UNMEASURED)

    @property
    def unmeasured(self) -> tuple[str, ...]:
        """Zondun ÖZÜ alınmadı — "hədəf vermir" demək OLMAZ."""
        return tuple(p.key for p in self.probes if p.status in UNMEASURED)

    @property
    def latency_profile(self) -> dict[str, Any]:
        if not self.latencies_ms:
            return {"samples": 0}
        ordered = sorted(self.latencies_ms)
        return {
            "samples": len(ordered),
            "min_ms": ordered[0],
            "median_ms": int(statistics.median(ordered)),
            "max_ms": ordered[-1],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "target_version": self.target_version,
            "probes": [p.to_dict() for p in self.probes],
            "field_status": self.field_status,
            "graders_available": list(self.graders_available),
            "graders_lost": list(self.graders_lost),
            "graders_unverified": list(self.graders_unverified),
            "unmeasured_probes": list(self.unmeasured),
            "latency_profile": self.latency_profile,
            "tokens": self.tokens,
            "requests_sent": self.requests_sent,
        }


# ============================================================ zondların qaçışı
def _request(query: str, session: str) -> AgentRequest:
    return AgentRequest(
        messages=[{"role": "user", "content": query}],
        session_id=session,
        metadata={"case_id": f"preflight-{session}"},
    )


def _multi_request(queries: Sequence[str], session: str) -> AgentRequest:
    return AgentRequest(
        messages=[{"role": "user", "content": q} for q in queries],
        session_id=session,
        metadata={"case_id": f"preflight-{session}"},
    )


def _field_probe(key: str, title: str, response: AgentResponse, present: bool,
                 detail_yes: Callable[[], str], detail_no: str) -> ProbeResult:
    """Bir sahənin görünüb-görünmədiyi. Cavabın özü sınıbsa `skipped`.

    Sınmış cavabdan "hədəf `usage` vermir" nəticəsi çıxarmaq YANLIŞ olardı:
    heç nə gəlməyib, sahə də gəlməyib.

    `detail_yes` ÇAĞIRILANDIR: mətn yalnız sahə mövcud olanda qurulur, yoxsa
    "birinci parçanın id-si" kimi izahlar boş siyahıda çökərdi.
    """
    if response.error and not response.text.strip():
        return ProbeResult(key, title, SKIPPED,
                           f"cavab alınmadı ({response.error}) — sahə ölçülmədi")
    return ProbeResult(
        key, title, YES if present else NO, detail_yes() if present else detail_no
    )


async def _probe_health(adapter: Any) -> ProbeResult:
    try:
        alive = await adapter.health()
    except Exception as exc:  # health() ATMAMALIDIR — atırsa bu, tapıntıdır
        return ProbeResult("health", "Hədəf əlçatandır", ERROR,
                           f"health() istisna atdı: {type(exc).__name__}: {exc}")
    return ProbeResult(
        "health", "Hədəf əlçatandır", YES if alive else NO,
        "health() True" if alive else "health() False — açar/ünvan yoxlanmalıdır",
    )


async def _probe_single_turn(adapter: Any, query: str) -> tuple[list[ProbeResult],
                                                               AgentResponse]:
    """Bir sorğu -> DÖRD ölçü (mətn, tool, retrieval, usage)."""
    response = await adapter.invoke(_request(query, "single"))
    has_text = bool(response.text.strip()) and response.error is None
    answer = ProbeResult(
        "answer", "Tək növbəli sorğuya mətn qaytarır",
        YES if has_text else (ERROR if response.error else NO),
        (f"{len(response.text)} simvol cavab" if has_text
         else f"cavab yoxdur: {response.error or 'boş mətn'}"),
        {"error": response.error, "error_class": response.error_class},
    )
    probes = [
        answer,
        _field_probe("tool_calls", "İcra olunan tool-lar görünür", response,
                     bool(response.tool_calls),
                     lambda: f"{len(response.tool_calls)} çağırış: "
                             + ", ".join(sorted({c.name for c in response.tool_calls})),
                     "cavabda tool çağırışı YOXDUR"),
        _field_probe("retrieved", "Retrieval parçaları görünür", response,
                     bool(response.retrieved),
                     lambda: f"{len(response.retrieved)} parça, id nümunəsi: "
                             f"{response.retrieved[0].chunk_id!r}",
                     "cavabda `retrieved[]` YOXDUR"),
        _field_probe("usage", "Token hesabı görünür", response,
                     response.usage is not None,
                     lambda: _usage_detail(response), "cavabda `usage` YOXDUR"),
        _probe_cost(response),
    ]
    return probes, response


#: Xərc zondunun həddi QƏSDƏN böyükdür: sual "ucuzdurmu" deyil, "hesablana
#: bilirmi"dir. Grader `skipped` verirsə ölçü YOXDUR — keçib-keçməməsi vacib deyil.
COST_PROBE_LIMIT_USD = 1000.0


def _probe_cost(response: AgentResponse) -> ProbeResult:
    """`cost_under` grader-inin ÖZ qərarı — proxy deyil, nəticə.

    Sahəyə baxmaq bəs etmir: `usage` gəlib model etiketi gəlmirsə (canlı
    Dify-da məhz belədir), grader qiymət cədvəlində model tapmır və `skipped`
    verir. Preflight "token görünür -> xərc ölçülür" desəydi, hesabatdakı
    bütün `cost_under` sətirləri gözlənilmədən `skipped` çıxardı.
    """
    from agentproof.graders import registry
    from agentproof.types import Case

    title = "Xərc hesablana bilir (`cost_under`)"
    if response.error and not response.text.strip():
        return ProbeResult("cost", title, SKIPPED,
                           f"cavab alınmadı ({response.error}) — xərc ölçülmədi")
    case = Case(id="preflight-cost", input="x", grader="cost_under",
                expect={"max_cost_usd": COST_PROBE_LIMIT_USD})
    result = registry.get("cost_under").grade(case, response)
    if result.skipped:
        return ProbeResult("cost", title, NO, result.reason, dict(result.evidence))
    cost = result.evidence.get("cost_usd")
    return ProbeResult("cost", title, YES,
                       f"bu zondun xərci ${cost:.6f}" if isinstance(cost, float)
                       else result.reason, dict(result.evidence))


def _usage_detail(response: AgentResponse) -> str:
    usage = response.usage
    if usage is None:  # pragma: no cover - çağıran yer artıq yoxlayıb
        return ""
    model = usage.model or UNKNOWN
    warning = "" if usage.model else " — model etiketi YOXDUR, `--model` verin"
    return (f"in={usage.input_tokens} out={usage.output_tokens}; "
            f"model etiketi: {model}{warning}")


async def _probe_multi_turn(adapter: Any, queries: Sequence[str], memo: str) -> tuple[
        ProbeResult, AgentResponse | None]:
    response = await adapter.invoke(_multi_request(queries, "multi"))
    title = "Çoxnövbəli söhbət zəncirlənir"
    if response.error == "multi_turn_unsupported":
        return ProbeResult("multi_turn", title, NO,
                           "adapter çoxnövbəli dəstəkləmir: "
                           f"{response.raw.get('detail', '')}",
                           {"request_sent": False}), None
    if response.error:
        return ProbeResult("multi_turn", title, ERROR,
                           f"söhbət sınadı: {response.error}",
                           {"error_class": response.error_class}), response
    remembered = memo in response.text
    chained = bool(response.raw.get("conversation_chained"))
    return ProbeResult(
        "multi_turn", title, YES if (remembered and chained) else NO,
        (f"{response.n_turns} növbə bir söhbətdə, son cavab {memo!r} nişanını xatırladı"
         if remembered and chained
         else f"zəncir={chained}, nişan xatırlanmadı ({memo!r} son cavabda yoxdur)"),
        {"n_turns": response.n_turns, "conversation_chained": chained,
         "remembered": remembered},
    ), response


def _collect(report: PreflightReport, response: AgentResponse | None) -> None:
    """Gecikmə və token uçotu — hesabatın "nə qədər tutdu" hissəsi."""
    if response is None:
        return
    report.requests_sent += max(response.attempts, 0)
    for turn in response.turns or [response]:
        if turn.latency_ms > 0:
            report.latencies_ms.append(turn.latency_ms)
    for usage in (response.usage, response.retry_usage):
        if usage is None:
            continue
        report.tokens["input"] = report.tokens.get("input", 0) + usage.input_tokens
        report.tokens["output"] = report.tokens.get("output", 0) + usage.output_tokens


async def run_preflight(
    adapter: Any,
    *,
    target: str,
    probe: str = DEFAULT_PROBE,
    follow_up: Sequence[str] | None = None,
    memo: str = DEFAULT_MEMO,
    multi_turn: bool = True,
) -> PreflightReport:
    """Zondları qaçırır. HEÇ BİR istisna yuxarı qalxmır — hesabat həmişə çıxır."""
    report = PreflightReport(
        target=target, target_version=str(getattr(adapter, "version", "") or UNKNOWN)
    )
    report.probes.append(await _probe_health(adapter))

    single, response = await _probe_single_turn(adapter, probe)
    report.probes.extend(single)
    _collect(report, response)

    if multi_turn:
        queries = list(follow_up or [q.format(memo=memo) for q in DEFAULT_FOLLOW_UP])
        multi, multi_response = await _probe_multi_turn(adapter, queries, memo)
        report.probes.append(multi)
        _collect(report, multi_response)
    else:
        report.probes.append(ProbeResult(
            "multi_turn", "Çoxnövbəli söhbət zəncirlənir", SKIPPED,
            "--no-multi-turn ilə keçildi — çoxnövbəli case-lər ÖLÇÜLMƏMİŞ qalır"))
    return report


# ================================================================== hesabat
_MARK = {YES: "bəli", NO: "XEYR", ERROR: "XƏTA", SKIPPED: "keçildi"}


def render_markdown(report: PreflightReport) -> str:
    """Müştəri sənədinə birbaşa köçürülə bilən mətn."""
    lines = [
        f"# Preflight — `{report.target}`",
        "",
        f"Hədəf versiyası: `{report.target_version}` · "
        f"göndərilən sorğu: {report.requests_sent}",
        "",
        "| # | Zond | Nəticə | Təfərrüat |",
        "|---|------|--------|-----------|",
    ]
    for index, probe in enumerate(report.probes, start=1):
        detail = probe.detail.replace("|", "\\|")
        lines.append(f"| {index} | {probe.title} | {_MARK[probe.status]} | {detail} |")

    lines += ["", "## Nəyi ÖLÇƏ BİLMİRİK", ""]
    losses = [(p, p.graders_lost) for p in report.probes if p.graders_lost]
    multi = report.by_key("multi_turn")
    if losses or (multi is not None and multi.status == NO):
        for probe, lost in losses:
            lines.append(f"- **{probe.title}: XEYR** → `{'`, `'.join(lost)}` işləmir "
                         f"(bütün belə case-lər `skipped` olacaq).")
        if multi is not None and multi.status == NO:
            lines.append("- **Çoxnövbəli case-lər ölçülmür**: kontekst itkisi (C1) "
                         "bu hədəfdə aşkarlana bilmir.")
    else:
        lines.append("- Təsdiqlənmiş məhdudiyyət yoxdur.")

    if report.unmeasured:
        lines += ["", "## Ölçülməmiş qalan zondlar", "",
                  "Bunlar hədəfin məhdudiyyəti DEYİL — zondun özü nəticə vermədi. "
                  "Nəticə çıxarmadan əvvəl təkrarlayın:", ""]
        for key in report.unmeasured:
            probe = report.by_key(key)
            lines.append(f"- `{key}`: {probe.detail if probe else ''}")
        if report.graders_unverified:
            lines.append("- Bu grader-lərin işləyəcəyi TƏSDİQLƏNMƏDİ: "
                         f"`{'`, `'.join(report.graders_unverified)}`")

    lines += ["", "## Təsdiqlənmiş işləyən grader-lər", "",
              ("`" + "`, `".join(report.graders_available) + "`")
              if report.graders_available else "- Yoxdur.",
              "", "## Gecikmə profili", ""]
    profile = report.latency_profile
    if profile["samples"]:
        lines.append(f"- {profile['samples']} ölçmə: min {profile['min_ms']} ms · "
                     f"median {profile['median_ms']} ms · maks {profile['max_ms']} ms")
        lines.append("- ⚠️ Bu, PAYLANMA deyil — bir neçə zondun ölçüsüdür. "
                     "Real profil tam qaçışdan çıxır.")
    else:
        lines.append("- Ölçmə yoxdur (heç bir zond cavab almadı).")
    if report.tokens:
        lines += ["", f"Zondların yandırdığı token: in={report.tokens.get('input', 0)} "
                      f"out={report.tokens.get('output', 0)}"]
    return "\n".join(lines) + "\n"


# ====================================================================== CLI
def build_adapter(target: str, config: dict[str, Any] | None = None) -> Any:
    """Adapteri mühit konfiqurasiyası ilə qurur.

    `callable` hədəfi mühit dəyişəni ilə qurula BİLMƏZ: onun konfiqurasiyası
    Python obyektidir. Səssizcə boş adapter qurmaq əvəzinə səbəb deyilir.
    """
    if target == "callable":
        raise SystemExit(
            "preflight: `callable` hədəfi CLI-dan qurula bilmir (fn bir Python "
            "obyektidir). Python-dan çağırın:\n"
            "    from agentproof.preflight import run_preflight, render_markdown\n"
            "    report = asyncio.run(run_preflight(adapter, target='callable'))"
        )
    return create_adapter(target, **{**adapter_config_from_env(target), **(config or {})})


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="agentproof.preflight",
        description="Hədəfin ölçüləbilirliyini auditdən əvvəl yoxlayır",
    )
    p.add_argument("--target", required=True, help="adapter adı (mock | dify_http | json_http)")
    p.add_argument("--probe", default=DEFAULT_PROBE,
                   help="tək növbəli zond sualı (bilik bazasına və tool-a toxunmalıdır)")
    p.add_argument("--follow-up", action="append", default=None,
                   help="çoxnövbəli zondun növbəsi (bir neçə dəfə verilə bilər)")
    p.add_argument("--memo", default=DEFAULT_MEMO,
                   help="çoxnövbəli zondda xatırlanmalı nişan")
    p.add_argument("--no-multi-turn", action="store_true",
                   help="çoxnövbəli zondu qaçırma (2 sorğuya qənaət)")
    p.add_argument("--model", default=os.environ.get("AGENTPROOF_SUT_MODEL", ""),
                   help="hədəfin içindəki model ETİKETİ (`usage.model` üçün)")
    p.add_argument("--out-md", default=None, help="markdown hesabatın yazılacağı fayl")
    p.add_argument("--out-json", default=None, help="JSON hesabatın yazılacağı fayl")
    p.add_argument("--json", dest="as_json", action="store_true",
                   help="stdout-a markdown yerinə JSON yaz")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config: dict[str, Any] = {"model": args.model} if args.model else {}
    adapter = build_adapter(args.target, config)
    report = asyncio.run(run_preflight(
        adapter,
        target=args.target,
        probe=args.probe,
        follow_up=args.follow_up,
        memo=args.memo,
        multi_turn=not args.no_multi_turn,
    ))
    markdown = render_markdown(report)
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    if args.out_md:
        Path(args.out_md).write_text(markdown, encoding="utf-8")
    if args.out_json:
        Path(args.out_json).write_text(payload + "\n", encoding="utf-8")
    print(payload if args.as_json else markdown)
    # Çıxış kodu: hədəf ÜMUMİYYƏTLƏ cavab vermirsə 1 — qapı kimi işlədilə bilsin.
    answer = report.by_key("answer")
    return 0 if answer is not None and answer.status == YES else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

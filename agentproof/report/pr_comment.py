"""PR şərhi — MÜTLƏQ rəqəm deyil, DƏYİŞİKLİK (STACK.md §8.5, harness-eng qaydası)."""

from __future__ import annotations

from agentproof.failure import REASON_HINT
from agentproof.graders.calibration import judge_status
from agentproof.report.baseline import GateResult
from agentproof.report.cost import summary_line
from agentproof.types import UNKNOWN, RepeatCheck, RunDelta, RunRecord


def skipped_lines(record: RunRecord, bullet: str = "  - ") -> list[str]:
    """Skipped-lər SƏBƏB SİNFİ üzrə (AP-024).

    Bir yığın `completion_request_error` oxucuya heç nə demir: gözləsin, yoxsa
    balans doldursun? Sinif məhz bunu deyir.
    """
    by_reason = record.totals.get("skipped_by_reason") or {}
    if not by_reason:
        return []
    return [
        f"{bullet}{reason}: {count} — {REASON_HINT.get(reason, '')}"
        for reason, count in by_reason.items()
    ]


def halt_lines(record: RunRecord, bullet: str = "  ") -> list[str]:
    """Qaçış yarıda dayandırılıbsa səbəb AÇIQ yazılır — gizlənə bilməz."""
    halted = record.totals.get("halted") or {}
    if not halted.get("halted"):
        return []
    reason = halted.get("reason", "")
    return [
        f"{bullet}⛔ QAÇIŞ DAYANDIRILDI — {reason}: {halted.get('hint', '')}",
        f"{bullet}   ilk görünmə: {halted.get('case_id') or '?'} · "
        f"{halted.get('detail', '')[:200]}",
        f"{bullet}   qalan case-lər hədəfə GÖNDƏRİLMƏDİ — nəticə TAM DEYİL.",
    ]


UNVERIFIED = "təsdiqlənməmiş"
#: Azərbaycan əlifbasında `i`.upper() -> `İ`; Python `I` verir, ona görə
#: böyük hərfli forma ƏLLƏ yazılır (`.upper()` «TƏSDIQLƏNMƏMIŞ» çıxarır).
UNVERIFIED_CAPS = "TƏSDİQLƏNMƏMİŞ"


def headline(delta: RunDelta) -> str:
    line = (
        f"{delta.pass_rate_before:.0%} → {delta.pass_rate_after:.0%} · "
        f"{len(delta.broken)} sındı · {len(delta.fixed)} düzəldi · "
        f"{delta.cost_delta:+.2f}$ · p95 {delta.p95_delta_ms / 1000:+.1f}s"
    )
    # `--repeat` uyğunsuzluğu BAŞLIQDA görünməlidir (AP-043): rəqəmləri oxuyan
    # adam onların nə qədər ölçmə ilə müdafiə olunduğunu elə burada bilməlidir.
    return line if delta.verified else f"{line} · ⚠️ {UNVERIFIED_CAPS}"


def repeat_line(check: RepeatCheck) -> str:
    """Bir sətirlik `--repeat` vəziyyəti (footer / konsol üçün)."""
    cur = "?" if check.current is None else f"{check.current}×"
    base = "?" if check.baseline is None else f"{check.baseline}×"
    text = f"təkrar {cur} (baseline {base})"
    if check.status == "fewer":
        return f"⚠️ {text} — AZ təkrar, müqayisə {UNVERIFIED}"
    if check.status == "unknown":
        return f"⚠️ {text} — NAMƏLUM, müqayisə {UNVERIFIED}"
    if check.status == "more":
        return f"{text} — baseline-dan çox təkrar"
    return text


def repeat_block(delta: RunDelta) -> list[str]:
    """`--repeat` xəbərdarlığı PR şərhinin BAŞINDA — gizlənə bilməz (AP-043)."""
    check = delta.repeat_check
    if check.verified or not check.warnings:
        return []
    claims = (
        f"{len(delta.fixed)} «düzəldi» · {len(delta.broken)} «sındı»"
        if (delta.fixed or delta.broken)
        else "aşağıdakı fərq iddiaları"
    )
    return [
        f"> ⚠️ **`--repeat` {'uyğunsuzluğu' if check.status == 'fewer' else 'naməlum'} "
        f"— {claims} TƏSDİQLƏNMƏMİŞDİR.**",
        ">",
        f"> {check.warnings[0]}",
        "",
    ]


def _case_list(record: RunRecord, case_ids: list[str], limit: int = 10) -> list[str]:
    reasons = {r.case_id: r.grade.reason for r in record.results}
    graders = {r.case_id: r.grade.grader for r in record.results}
    lines = [
        f"- `{cid}` ({graders.get(cid, '?')}) — {reasons.get(cid, '')}"
        for cid in case_ids[:limit]
    ]
    if len(case_ids) > limit:
        lines.append(f"- … və daha {len(case_ids) - limit} case")
    return lines


def judge_block(record: RunRecord) -> list[str]:
    """Judge kalibrasiya bölməsi — judge grader-i işlədilibsə MƏCBURİ görünür.

    Bu bölmə `totals["judge"]`-dan gəlir və `normalize.py` onu avtomatik
    doldurur. Kalibrasiya faylı yoxdursa, xəbərdarlıq göstərilir — susmaq
    variantı yoxdur (FAILURE-TAXONOMY §10 Boşluq 7).
    """
    status = record.totals.get("judge")
    if not isinstance(status, dict):
        status = judge_status(r.grade.grader for r in record.results)
    if not status.get("used"):
        return []
    graders = ", ".join(f"`{g}`" for g in status.get("graders", []))
    if not status.get("calibrated"):
        return ["### Judge kalibrasiyası", "", status["warning"], "", f"Judge grader-ləri: {graders}", ""]
    out = [
        "### Judge kalibrasiyası",
        "",
        status["summary"],
        "",
        f"Judge grader-ləri: {graders} · etiket dəsti `{status.get('labels_sha256', '')[:12]}`",
        "",
    ]
    if status.get("blocking_reasons"):
        out += [f"- ⚠️ {r}" for r in status["blocking_reasons"]] + [""]
    return out


def render(
    delta: RunDelta,
    current: RunRecord,
    gate_result: GateResult | None = None,
) -> str:
    status = "✅ keçdi" if (gate_result is None or gate_result.passed) else "❌ bloklandı"
    totals = current.totals
    out: list[str] = [
        "## AgentProof eval",
        "",
        f"**{headline(delta)}** — {status}",
        "",
        f"Hədəf: `{current.target}@{current.target_version or '?'}` · "
        f"dataset `{current.dataset_hash}` · "
        f"{totals.get('n_graded', 0)} qiymətləndirilən case"
        + (f" · {totals.get('n_skipped', 0)} skipped" if totals.get("n_skipped") else ""),
        "",
    ]

    halted = totals.get("halted") or {}
    if halted.get("halted"):
        out += [
            f"> ⛔ **Qaçış yarıda dayandırıldı — `{halted.get('reason', '')}`.** "
            f"{halted.get('hint', '')}",
            ">",
            f"> İlk görünmə: `{halted.get('case_id') or '?'}` · "
            f"{halted.get('detail', '')[:200]}",
            ">",
            "> Qalan case-lər hədəfə göndərilmədi — bu nəticə TAM DEYİL.",
            "",
        ]

    out += repeat_block(delta)

    reasons = skipped_lines(current, bullet="- ")
    if reasons:
        out += ["**Skipped səbəbləri:**", "", *reasons, ""]

    cov = totals.get("cost_coverage") or {}
    if cov.get("status") not in (None, "complete"):
        out += [
            f"**Xərc:** {summary_line(totals)} — "
            f"{cov.get('unmeasured_attempts', 0)}/{cov.get('attempts', 0)} cəhd ölçülmədi "
            f"({cov.get('note', '')}).",
            "",
        ]

    if gate_result is not None and not gate_result.passed:
        out += ["**Bloklama səbəbləri:**", ""]
        out += [f"- {r}" for r in gate_result.reasons]
        out += [""]

    # Az (və ya naməlum) təkrarla ölçülmüş fərq iddiaları BAŞLIQDA işarələnir:
    # oxucu «1 düzəldi» sətrini kontekstsiz oxumamalıdır (AP-043).
    mark = "" if delta.verified else f" — ⚠️ {UNVERIFIED_CAPS}"
    if delta.broken:
        out += [f"### 🔴 Sınan ({len(delta.broken)}){mark}", ""]
        out += _case_list(current, delta.broken)
        out += [""]
    if delta.fixed:
        out += [f"### 🟢 Düzələn ({len(delta.fixed)}){mark}", ""]
        out += [f"- `{cid}`" for cid in delta.fixed[:10]]
        out += [""]
    if delta.flaky:
        out += [
            f"### 🟡 Qeyri-sabit / flaky ({len(delta.flaky)})",
            "",
            "Reqressiya sayılmır — `--repeat` qaçışında dəyişkən nəticə verdi.",
            "",
        ]
        out += [f"- `{cid}`" for cid in delta.flaky[:10]]
        out += [""]
    if delta.still_failing:
        out += [f"<details><summary>Hələ də sınıq ({len(delta.still_failing)})</summary>", ""]
        out += _case_list(current, delta.still_failing, limit=25)
        out += ["", "</details>", ""]
    if delta.new_cases or delta.removed_cases:
        out += [
            f"Dataset dəyişdi: +{len(delta.new_cases)} yeni, "
            f"−{len(delta.removed_cases)} silinmiş case",
            "",
        ]

    out += judge_block(current)
    out += retrieval_block(current)
    out += anchor_block(current)

    out += [
        "---",
        f"<sub>model: {model_line(current)} · "
        f"retrieval: {retrieval_line(current)} · "
        f"lane: {totals.get('lanes', 1)} · "
        f"{repeat_line(delta.repeat_check)} · "
        f"xərc ${totals.get('cost_usd', 0):.2f} "
        f"(+${float(totals.get('wasted_cost_usd', 0.0) or 0.0):.2f} yandırılmış) · "
        f"p50 {totals.get('p50_latency_ms', 0) / 1000:.1f}s · "
        f"p95 {totals.get('p95_latency_ms', 0) / 1000:.1f}s · "
        f"qiymət cədvəli {totals.get('price_table_as_of', '?')}</sub>",
    ]
    return "\n".join(out)


def model_line(record: RunRecord) -> str:
    """`usage.model` yoxlanıbmı — hesabatda GİZLƏNMƏMƏLİDİR.

    Yoxlanmamış etiket, xərcin yanlış modelə yazıla biləcəyi deməkdir; bu, boş
    xərcdən pisdir, çünki rəqəm inandırıcı görünür.
    """
    check = record.totals.get("model_check") or {}
    name = record.model or check.get("actual") or check.get("declared") or "?"
    status = check.get("status", "")
    if status == "match":
        return f"{name} (app konfiqurasiyası ilə yoxlanıldı)"
    if status == "adopted":
        return f"{name} (app konfiqurasiyasından götürüldü)"
    if not status:
        return f"{name} (YOXLANILMAMIŞ əl etiketi)"
    return f"{name} (YOXLANILMADI — {check.get('detail', status)})"


def retrieval_line(record: RunRecord) -> str:
    """Embedder + faktiki `top_k` — konfiqurasiya oxunmayıbsa XƏBƏRDARLIQ.

    LIM-E06: bu iki parametr olmadan tapıntılar yenidən yoxlana bilmir. Səssiz
    default vermək burada ən pis variantdır — rəqəm inandırıcı görünür, amma
    hansı konfiqurasiyaya aid olduğu sübut edilə bilmir (VALID-03).
    """
    check = record.totals.get("retrieval_check") or {}
    status = check.get("status", "")
    top_k = record.effective_top_k
    top_k_text = UNKNOWN if top_k is None else str(top_k)
    line = f"{record.embedding_model} · top_k {top_k_text}"
    if record.reranking_enabled is not None:
        line += f" · rerank {'açıq' if record.reranking_enabled else 'yox'}"
    if not status:
        return f"{line} (QEYD OLUNMAYIB — köhnə artefakt və ya yoxlama qaçmadı)"
    if status == "live":
        source = check.get("dataset_source", "")
        origin = "app-ın bağlı olduğu dataset" if source == "app-config" else f"dataset ({source})"
        return f"{line} (canlı oxundu — {origin} `{check.get('dataset_id', '')[:8]}`)"
    if status == "skipped":
        return f"{line} (YOXLANILMADI — {check.get('detail', 'bilərəkdən keçilib')})"
    warnings = check.get("warnings") or []
    head = warnings[0] if warnings else check.get("detail", status)
    more = f" · +{len(warnings) - 1} xəbərdarlıq" if len(warnings) > 1 else ""
    return f"{line} (⚠️ {head}{more})"


def retrieval_block(record: RunRecord) -> list[str]:
    """PR şərhində bütün retrieval xəbərdarlıqları — biri də gizlənmir."""
    check = record.totals.get("retrieval_check") or {}
    warnings = check.get("warnings") or []
    if not warnings:
        return []
    return [
        "### ⚠️ Retrieval konfiqurasiyası",
        "",
        *[f"- {w}" for w in warnings],
        "",
    ]


def anchor_line(record: RunRecord) -> str:
    """Lövbər xəritəsi ↔ dataset uyğunluğu (AP-022).

    Bayat xəritə retrieval case-lərini `0/k` ilə sındırır və hesabat bunu
    «retrieval işləmir» kimi göstərir (A-19). Yoxlanmadığı hal GİZLƏNMİR.
    """
    check = record.totals.get("anchor_check") or {}
    status = check.get("status", "")
    if not status:
        return "QEYD OLUNMAYIB (köhnə artefakt və ya yoxlama qaçmadı)"
    if status == "match":
        return (
            f"uyğun — dataset `{str(check.get('live_dataset_id', ''))[:8]}` · "
            f"{check.get('n_anchored_cases', 0)} lövbərli case"
        )
    if status == "no-retrieval":
        return "tətbiq olunmur (seçimdə retrieval case-i yoxdur)"
    if status == "skipped":
        return "⚠️ YOXLANILMADI — `--skip-anchor-check` ilə bilərəkdən keçilib"
    warnings = check.get("warnings") or []
    return f"⚠️ {warnings[0] if warnings else check.get('detail', status)}"


def anchor_block(record: RunRecord) -> list[str]:
    """PR şərhində lövbər xəbərdarlıqları — biri də gizlənmir."""
    check = record.totals.get("anchor_check") or {}
    warnings = check.get("warnings") or []
    if not warnings:
        return []
    return [
        "### ⚠️ Lövbər xəritəsi",
        "",
        *[f"- {w}" for w in warnings],
        "",
    ]


def _coverage_console(totals: dict) -> list[str]:
    """Ölçülməyən xərc AÇIQ yazılır — sıfır kimi görünməsin (AP-026)."""
    cov = totals.get("cost_coverage") or {}
    if not cov or cov.get("status") == "complete":
        return []
    return [
        f"            ⚠️ {cov.get('unmeasured_attempts', 0)}/{cov.get('attempts', 0)} "
        f"cəhdin xərci ölçülmədi — {cov.get('note', '')}"
    ]


def render_console(record: RunRecord, delta: RunDelta | None = None) -> str:
    """Baseline olmadan da işləyən insan üçün konsol xülasəsi."""
    t = record.totals
    lines = [
        f"AgentProof · {record.target}@{record.target_version or '?'} · dataset {record.dataset_hash}",
        f"  keçdi   : {t.get('n_passed', 0)}/{t.get('n_graded', 0)}  ({t.get('pass_rate', 0):.1%})",
        f"  sındı   : {t.get('n_failed', 0)}",
        f"  skipped : {t.get('n_skipped', 0)}  (qiymətləndirilə bilmədi — səssiz keçmə deyil)",
        *skipped_lines(record, bullet="            · "),
        f"  xərc    : {summary_line(t)}",
        f"            (qiymət cədvəli {t.get('price_table_as_of', '?')} · "
        f"dərəcə tarixi {t.get('priced_on', '?')})",
        *_coverage_console(t),
        f"  model   : {model_line(record)}",
        f"  retrieval: {retrieval_line(record)}",
        f"  lövbər  : {anchor_line(record)}",
        f"  gecikmə : p50 {t.get('p50_latency_ms', 0):.0f} ms · p95 {t.get('p95_latency_ms', 0):.0f} ms",
        f"  növbə   : {t.get('multi_turn_cases', 0)} çoxnövbəli case zəncirləndi",
    ]
    failed = [r for r in record.results if not r.grade.passed and not r.grade.skipped]
    if failed:
        lines.append("  sınan case-lər:")
        for r in failed[:15]:
            lines.append(f"    - {r.case_id} [{r.grade.grader}] {r.grade.reason}")
        if len(failed) > 15:
            lines.append(f"    … və daha {len(failed) - 15}")
    judge = record.totals.get("judge")
    if not isinstance(judge, dict):
        judge = judge_status(r.grade.grader for r in record.results)
    if judge.get("used"):
        lines.append(
            "  judge   : " + (judge["summary"] if judge.get("calibrated") else judge["warning"])
        )
    if delta is not None:
        lines.append(f"  baseline: {headline(delta)}")
        lines.append(f"  təkrar  : {repeat_line(delta.repeat_check)}")
        # Xəbərdarlığın TAM mətni konsolda da görünür — PR şərhini açmadan
        # «düzəldi» yazısına inanmaq üçün səbəb qalmasın (AP-043).
        for warning in delta.repeat_check.warnings:
            lines.append(f"            ⚠️ {warning}")
    lines += halt_lines(record)
    return "\n".join(lines)

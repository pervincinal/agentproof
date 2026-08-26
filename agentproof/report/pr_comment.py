"""PR şərhi — MÜTLƏQ rəqəm deyil, DƏYİŞİKLİK (STACK.md §8.5, harness-eng qaydası)."""

from __future__ import annotations

from agentproof.graders.calibration import judge_status
from agentproof.report.baseline import GateResult
from agentproof.types import RunDelta, RunRecord


def headline(delta: RunDelta) -> str:
    return (
        f"{delta.pass_rate_before:.0%} → {delta.pass_rate_after:.0%} · "
        f"{len(delta.broken)} sındı · {len(delta.fixed)} düzəldi · "
        f"{delta.cost_delta:+.2f}$ · p95 {delta.p95_delta_ms / 1000:+.1f}s"
    )


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

    if gate_result is not None and not gate_result.passed:
        out += ["**Bloklama səbəbləri:**", ""]
        out += [f"- {r}" for r in gate_result.reasons]
        out += [""]

    if delta.broken:
        out += [f"### 🔴 Sınan ({len(delta.broken)})", ""]
        out += _case_list(current, delta.broken)
        out += [""]
    if delta.fixed:
        out += [f"### 🟢 Düzələn ({len(delta.fixed)})", ""]
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

    out += [
        "---",
        f"<sub>xərc ${totals.get('cost_usd', 0):.2f} · "
        f"p50 {totals.get('p50_latency_ms', 0) / 1000:.1f}s · "
        f"p95 {totals.get('p95_latency_ms', 0) / 1000:.1f}s · "
        f"qiymət cədvəli {totals.get('price_table_as_of', '?')}</sub>",
    ]
    return "\n".join(out)


def render_console(record: RunRecord, delta: RunDelta | None = None) -> str:
    """Baseline olmadan da işləyən insan üçün konsol xülasəsi."""
    t = record.totals
    lines = [
        f"AgentProof · {record.target}@{record.target_version or '?'} · dataset {record.dataset_hash}",
        f"  keçdi   : {t.get('n_passed', 0)}/{t.get('n_graded', 0)}  ({t.get('pass_rate', 0):.1%})",
        f"  sındı   : {t.get('n_failed', 0)}",
        f"  skipped : {t.get('n_skipped', 0)}  (qiymətləndirilə bilmədi — səssiz keçmə deyil)",
        f"  xərc    : ${t.get('cost_usd', 0):.4f}  (qiymət cədvəli {t.get('price_table_as_of', '?')})",
        f"  gecikmə : p50 {t.get('p50_latency_ms', 0):.0f} ms · p95 {t.get('p95_latency_ms', 0):.0f} ms",
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
    return "\n".join(lines)

"""Aqreqat grader: consistency_at_k.

`--repeat N` ilə alınan k cavabın nə qədər sabit olduğunu ölçür.
Determinist qalır — LLM-judge YOXDUR, şəbəkəyə çıxmır (STACK.md §8.3).

ÖLÇDÜYÜ ŞEY: eyni QƏRARmı, eyni SÖZLƏRmi yox.
Pilotda (T-07) üç cavab eyni qərarı verdi ("Aurora-brand, 24 ay") amma grader
`24 months` ilə `24-month`-u fərqli saydı və cavabdakı tarixləri fakt kimi
topladı — nəticədə 0.67/0.33 verdi. Bu, O1-i (qeyri-determinizm) ölçmür,
ifadə sərbəstliyini ölçür. Ona görə:

  1. Bütün rejimlər `graders/canonical.py` normallaşdırma qatından keçir.
  2. `verdict` rejimi (ƏSAS) — qərarın ölçüləri case `expect`-ində AÇIQ
     elan olunur. Grader özbaşına bütün rəqəmləri toplamır.
  3. `numbers` / `normalized` səth metrikləridir — `evidence.surface`-də
     həmişə hesabatlanır, amma bal onlardan gəlmir.

Rejimlər:
  verdict     — elan olunmuş qərar sahələri (ən müdafiəolunan, tövsiyə olunan)
  key_facts   — `expect.key_facts` ifadələrinin var/yox vektoru (kanonik)
  numbers     — kanonik kəmiyyət dəsti (SƏTH; tarixlər daxil deyil)
  normalized  — normallaşdırılmış mətnin eyniliyi (ƏN SƏRT SƏTH)
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from agentproof.graders.base import grader
from agentproof.graders.canonical import (
    Analysis,
    analyze,
    canonical_text,
    cue_matches,
    parse_quantity,
)
from agentproof.types import AgentResponse, Case, GradeResult

_ABSENT = "<oxunmadı>"
"""Slot cavabda oxunmadı. `None` deyil — imzada görünən açıq dəyər."""


# ------------------------------------------------------------------- slotlar
def _quantity_slot(a: Analysis, spec: dict[str, Any]) -> tuple[str, ...]:
    """Qərar üçün əhəmiyyətli kəmiyyət(lər).

    `near`  — kəmiyyətin ÖZ BƏNDİNDƏ olmalı olan işarə sözlər (yoxdursa filtr yoxdur).
    `not_near` — kəmiyyətdən ±`window` token məsafədə (bənd hüdudunda) olmamalıdır.

    Bənd + pəncərə ayrılığı qəsdlidir: "24-month Aurora-brand warranty, since it
    was delivered before the superseded 18-month provision" cümləsində hər iki
    rəqəm eyni bənddədir, amma yalnız 18-in yanında `superseded` var.
    """
    unit = spec.get("unit")
    near = [str(c) for c in spec.get("near", [])]
    not_near = [str(c) for c in spec.get("not_near", [])]
    window = int(spec.get("window", 4))
    found: list[str] = []
    for lo, hi in a.clauses:
        clause = a.span(lo, hi)
        if near and not any(cue_matches(clause, c) for c in near):
            continue
        for i in range(lo, hi):
            q = a.tokens[i].quantity
            if q is None or (unit and q.unit != unit):
                continue
            if not_near:
                win = a.span(max(lo, i - window), min(hi, i + window + 1))
                if any(cue_matches(win, c) for c in not_near):
                    continue
            found.append(q.key)
    return tuple(sorted(set(found)))


def _label_slot(a: Analysis, spec: dict[str, Any], slot: str) -> tuple[str, ...]:
    """Hansı qaydaya istinad edilib — etiket → işarə ifadələri."""
    labels = spec.get("labels")
    if not isinstance(labels, dict) or not labels:
        raise ValueError(f"verdict slot '{slot}': type='label' üçün `labels` xəritəsi məcburidir")
    return tuple(
        sorted(
            name
            for name, cues in labels.items()
            if any(cue_matches(a.text, str(c)) for c in (cues or []))
        )
    )


def _slot_value(a: Analysis, slot: str, spec: dict[str, Any]) -> tuple[str, ...] | str:
    stype = spec.get("type", "quantity")
    if stype == "quantity":
        value = _quantity_slot(a, spec)
    elif stype == "label":
        value = _label_slot(a, spec, slot)
    else:
        raise ValueError(
            f"verdict slot '{slot}': naməlum type={stype!r} (gözlənilən: 'quantity' | 'label')"
        )
    return value if value else _ABSENT


def _verdict_signature(
    a: Analysis, verdict: dict[str, dict[str, Any]]
) -> tuple[tuple[str, Any], ...]:
    return tuple((slot, _slot_value(a, slot, verdict[slot])) for slot in sorted(verdict))


# -------------------------------------------------------- səth (ikinci dərəcə)
def _numbers_signature(a: Analysis, units: list[str] | None) -> tuple[str, ...]:
    """Hansı rəqəmlər deyilib — DƏST kimi.

    Təkrar sayı səth detalıdır: bir cavab `24 ay`-ı iki dəfə, digəri bir dəfə
    desə, bu fakt fərqi deyil.
    """
    return tuple(
        sorted({q.key for q in a.quantities if not units or q.unit in units})
    )


def _normalized_signature(a: Analysis) -> tuple[str, ...]:
    return (" ".join(t.text for t in a.tokens),)


def _key_facts_signature(a: Analysis, key_facts: list[str]) -> tuple[bool, ...]:
    """Fakt təmiz kəmiyyətdirsə kanonik müqayisə, deyilsə mətn axtarışı.

    Bu sayədə `"24 month"` cavabdakı `24-month`, `24 months`, `24 mo` ilə uyğun gəlir.
    """
    present: list[bool] = []
    quantities = {q.key for q in a.quantities}
    for fact in key_facts:
        q = parse_quantity(fact)
        if q is not None:
            present.append(q.key in quantities)
        else:
            present.append(canonical_text(fact) in a.text)
    return tuple(present)


def _agreement(signatures: list[Any]) -> tuple[float, int, int, Any]:
    """(razılıq nisbəti, çoxluq sayı, fərqli variant sayı, çoxluq imzası)."""
    counts = Counter(signatures)
    top_sig, top_n = counts.most_common(1)[0]
    return top_n / len(signatures), top_n, len(counts), top_sig


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    return value


@grader
class ConsistencyAtK:
    """k cavabın çoxluq qrupu `min_agreement`-i keçməlidir.

    expect:
      mode: "verdict" | "key_facts" | "numbers" | "normalized"
            — default: `verdict` varsa "verdict", yoxsa "numbers"
      min_agreement: float   — default 1.0 (tam sabitlik)
      min_responses: int     — default 2

      verdict: {slot: spec}  — mode="verdict" üçün məcburi
        spec (type="quantity", default):
          unit: str          — "month" | "day" | "percent" | "usd" | ... (opsional)
          near: [str]        — kəmiyyətin bəndində olmalı olan işarələr (`warrant*`)
          not_near: [str]    — kəmiyyətin yaxınlığında OLMAMALI işarələr
          window: int        — not_near pəncərəsi, default 4 token
        spec (type="label"):
          labels: {ad: [ifadə]}

      key_facts: [str]       — mode="key_facts" üçün məcburi
      units: [str]           — mode="numbers" üçün opsional filtr
    """

    name = "consistency_at_k"
    kind = "deterministic"

    def grade_many(self, case: Case, responses: list[AgentResponse]) -> GradeResult:
        verdict = case.expect.get("verdict")
        mode = case.expect.get("mode", "verdict" if verdict else "numbers")
        threshold = float(case.expect.get("min_agreement", 1.0))
        key_facts = [str(f) for f in case.expect.get("key_facts", [])]
        units = [str(u) for u in case.expect.get("units", [])] or None
        min_responses = int(case.expect.get("min_responses", 2))

        if mode == "key_facts" and not key_facts:
            raise ValueError(
                f"case '{case.id}': consistency_at_k mode='key_facts' üçün `expect.key_facts` məcburidir"
            )
        if mode == "verdict" and not (isinstance(verdict, dict) and verdict):
            raise ValueError(
                f"case '{case.id}': consistency_at_k mode='verdict' üçün `expect.verdict` məcburidir "
                "— qərarın hansı ölçüləri sayıldığını case elan etməlidir"
            )
        if mode not in {"verdict", "key_facts", "numbers", "normalized"}:
            raise ValueError(f"case '{case.id}': naməlum consistency_at_k mode={mode!r}")
        if len(responses) < min_responses:
            return GradeResult.skip(
                self.name,
                f"consistency@k üçün ən azı {min_responses} cavab lazımdır, {len(responses)} var "
                "(--repeat N verilməyib?)",
                {"n_responses": len(responses)},
            )

        analyses = [analyze(r.text) for r in responses]

        # Səth metrikləri HƏMİŞƏ hesablanır — hesabatda ikinci dərəcəli göstərici.
        surface = {
            "numbers_agreement": _agreement([_numbers_signature(a, units) for a in analyses])[0],
            "normalized_agreement": _agreement([_normalized_signature(a) for a in analyses])[0],
        }

        if mode == "verdict":
            signatures: list[Any] = [_verdict_signature(a, verdict) for a in analyses]
            unreadable = {
                slot: [i for i, s in enumerate(signatures) if dict(s)[slot] == _ABSENT]
                for slot in verdict
            }
            dead = [
                slot
                for slot, idx in unreadable.items()
                if len(idx) == len(signatures) and verdict[slot].get("required", True)
            ]
            if dead:
                # HAMISINDA boşdursa bu "hamı razıdır" DEYİL — grader qərar verə bilmir.
                return GradeResult.skip(
                    self.name,
                    f"verdict slot(ları) heç bir cavabda oxunmadı: {dead} — ya cavablar "
                    "qərarı demir, ya slot spesifikasiyası yanlışdır. Sabitlik ölçülmədi.",
                    {"mode": mode, "unreadable": unreadable, "surface": surface},
                )
        elif mode == "key_facts":
            signatures = [_key_facts_signature(a, key_facts) for a in analyses]
            unreadable = {}
        elif mode == "numbers":
            signatures = [_numbers_signature(a, units) for a in analyses]
            unreadable = {}
        else:
            signatures = [_normalized_signature(a) for a in analyses]
            unreadable = {}

        agreement, majority_n, n_variants, top_sig = _agreement(signatures)
        passed = agreement >= threshold
        partial = sorted(s for s, idx in (unreadable or {}).items() if idx)
        note = f" · qismən oxunmayan slot(lar): {partial}" if partial else ""
        return GradeResult(
            passed=passed,
            score=agreement,
            grader=self.name,
            reason=(
                f"{len(signatures)} cavabdan {majority_n}-i eyni qərarı verir "
                f"(agreement {agreement:.2f} >= {threshold:.2f}, mode={mode}){note}"
                if passed
                else f"qeyri-sabit qərar: agreement {agreement:.2f} < {threshold:.2f} "
                f"(mode={mode}, {n_variants} fərqli variant){note}"
            ),
            evidence={
                "mode": mode,
                "agreement": agreement,
                "threshold": threshold,
                "n_variants": n_variants,
                "majority_signature": _jsonable(top_sig),
                "signatures": [_jsonable(s) for s in signatures],
                "unreadable_slots": {k: v for k, v in (unreadable or {}).items() if v},
                "surface": surface,
                "answers": [r.text[:200] for r in responses],
            },
        )

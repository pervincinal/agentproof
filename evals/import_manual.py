#!/usr/bin/env python3
"""Əl ilə yazılmış transkripti qrader zəncirinə verir (AP-071).

NİYƏ VAR. `docs/PREAUDIT-ENTRYPOINT.md` §B: hədəf şirkətin yalnız veb-vidceti
varsa və şərtləri avtomatlaşdırmanı qadağan edirsə, sualları **əl ilə** yazırıq.
Amma qradersiz «tapıntı» sadəcə mənim fikrimdir. Bu skript əl ilə toplanmış
cavabları eyni qraderlərdən, eyni təkrarlanma qapısından keçirir — yəni sorğunu
insan göndərir, **hökmü yenə kod verir**.

NƏYİ ÖLÇMÜR. Vidcetdən alınan cavabda `usage`, `retrieved`, `tool_calls` və
gecikmə YOXDUR. Onlar sıfır YAZILMIR — `None` / boş qalır və artefaktda
`measured: false` ilə işarələnir. `cost_under` qraderi bu halda `skipped`
qaytarır, yəni ölçülməyən şey yaşıl görünmür.

NECƏ FƏRQLƏNİR. `target` sahəsi `manual:<ad>` olur və `totals["source"]`
`manual_transcript`-dir. Əl ilə qaçışı avtomatik qaçışla qarışdırmaq hesabatı
etibarsız edərdi.

    python3 evals/import_manual.py transcript.yaml --dataset evals/datasets/full.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
import uuid
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from agentproof.deflection import check as deflection_check  # noqa: E402
from agentproof.graders import registry  # noqa: E402
from agentproof.types import (  # noqa: E402
    AgentResponse,
    Case,
    CaseResult,
    RunRecord,
)

#: Transkriptdə YAZILA BİLMƏYƏN sahələr. Əl ilə test onları ölçmür və
#: «bilmirəm» ilə «sıfır» arasındakı fərq bu layihənin əsas qaydasıdır.
UNMEASURABLE = ("usage", "cost_usd", "latency_ms", "retrieved", "tool_calls")

#: Şablonda doldurulmamış sahənin markeri.
PLACEHOLDER = "<<PASTE AGENT ANSWER>>"



# ------------------------------------------------------- düz mətn formatı
#: Case blokunun başlanğıcı: `=== <case_id> #<attempt>`
_BLOCK = re.compile(r"^===\s+(\S+)\s+#(\d+)\s*$")
#: Bu sətirdən SONRAKI hər şey cavabdır.
_ANSWER_MARK = "CAVAB:"


def parse_text(raw: str) -> dict[str, Any]:
    """Düz mətn transkriptini oxuyur.

    NİYƏ YAML DEYİL: agentin cavabında dırnaq, iki nöqtə, mötərizə və sətir
    keçidi olur. Onu YAML sətrinə yapışdırmaq faylı sındırır və insan
    ortada qalır. Burada cavab sərbəst mətndir — heç nə escape edilmir.
    """
    meta: dict[str, str] = {}
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    collecting = False

    for line in raw.splitlines():
        m = _BLOCK.match(line)
        if m:
            if current is not None:
                entries.append(current)
            current = {"case_id": m.group(1), "attempt": int(m.group(2)), "text": ""}
            collecting = False
            continue
        if current is None:
            if line.startswith("@"):
                key, _, val = line[1:].partition(" ")
                meta[key.strip()] = val.strip()
            continue
        if not collecting:
            if line.strip() == _ANSWER_MARK:
                collecting = True
            continue
        current["text"] += line + "\n"

    if current is not None:
        entries.append(current)

    for e in entries:
        e["text"] = e["text"].strip()

    return {
        "target": meta.get("target", ""),
        "demo_url": meta.get("url", ""),
        "tested_at": meta.get("date", ""),
        "tester": meta.get("tester", ""),
        "note": meta.get("note", ""),
        "responses": entries,
    }


def read_transcript(path: pathlib.Path) -> dict[str, Any]:
    raw = path.read_text()
    if path.suffix.lower() in (".txt", ".md") or raw.lstrip().startswith("==="):
        return parse_text(raw)
    if "\n=== " in raw:
        return parse_text(raw)
    return yaml.safe_load(raw)


def load_cases(dataset: pathlib.Path) -> dict[str, Case]:
    cases: dict[str, Case] = {}
    for line in dataset.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        raw = json.loads(line)
        cases[raw["id"]] = Case.from_dict(raw)
    return cases


def _reject_invented_values(entry: dict[str, Any], where: str) -> None:
    """Ölçülə bilməyən sahə transkriptdə yazılıbsa — DAYAN.

    Bu, əsas qorumadır. Kimsə `latency_ms: 0` və ya `cost_usd: 0` yazsa,
    hesabat «ölçdük, sıfır çıxdı» deyərdi. Ölçmədik.
    """
    invented = [k for k in UNMEASURABLE if k in entry]
    if invented:
        raise SystemExit(
            f"{where}: bu sahələr əl ilə testdə ÖLÇÜLMÜR və yazıla bilməz: "
            f"{', '.join(invented)}\n"
            "  Onlar artefaktda `None` qalır və hesabatda «ölçülmədi» görünür.\n"
            "  Sıfır yazmaq «ölçdük, sıfır çıxdı» demək olardı — bu, yalandır."
        )


def build(transcript: dict[str, Any], cases: dict[str, Case]) -> RunRecord:
    name = transcript.get("target")
    if not name:
        raise SystemExit("transkriptdə `target` yoxdur (şirkət adı)")
    entries = transcript.get("responses") or []
    if not entries:
        raise SystemExit("transkriptdə `responses` boşdur")

    grouped: dict[str, list[tuple[int, AgentResponse]]] = {}
    for i, entry in enumerate(entries):
        where = f"responses[{i}]"
        _reject_invented_values(entry, where)
        case_id = entry.get("case_id")
        if case_id not in cases:
            raise SystemExit(f"{where}: datasetdə belə case yoxdur: {case_id!r}")
        if "text" not in entry:
            raise SystemExit(f"{where}: `text` yoxdur")
        text = str(entry["text"])
        # Doldurulmamış şablon qiymətləndirilsə, boş mətn bütün inkar
        # assertion-larından KEÇƏR və mövcud olmayan tapıntı yaradardı.
        if not text.strip():
            raise SystemExit(
                f"{where} ({entry.get('case_id')}): `text` BOŞDUR.\n"
                "  Doldurulmamış şablon qiymətləndirilmir — boş cavab "
                "uydurma tapıntı yaradır."
            )
        if PLACEHOLDER in text:
            raise SystemExit(
                f"{where} ({entry.get('case_id')}): {PLACEHOLDER!r} hələ "
                "yerindədir — agentin cavabı köçürülməyib."
            )
        response = AgentResponse(
            text=text,
            raw={
                "source": "manual_transcript",
                "measured": False,
                "collected_by": transcript.get("tester", ""),
                "demo_url": transcript.get("demo_url", ""),
                "note": entry.get("note", ""),
            },
        )
        grouped.setdefault(case_id, []).append((int(entry.get("attempt", 1)), response))

    results: list[CaseResult] = []
    for case_id, attempts in grouped.items():
        case = cases[case_id]
        grader = registry.get(case.grader)
        for attempt, response in sorted(attempts):
            # Yönləndirmə qraderdən ƏVVƏL yoxlanır: boş məzmun bütün
            # `contains_none` yoxlamalarından keçər və yalançı yaşıl verər.
            grade = deflection_check(response, case.grader)
            if grade is None:
                if registry.is_aggregate(case.grader):
                    grade = grader.grade_many(case, [response])  # type: ignore[union-attr]
                else:
                    grade = grader.grade(case, response)  # type: ignore[union-attr]
            results.append(
                CaseResult(
                    case_id=case_id,
                    response=response,
                    grade=grade,
                    cost_usd=None,          # ölçülmədi — sıfır DEYİL
                    latency_ms=0,           # sxem int tələb edir; `measured: false` izah edir
                    attempt=attempt,
                    tags=list(case.tags),
                    severity=case.severity,
                )
            )

    selected = sorted(grouped)
    digest = hashlib.sha256("\n".join(selected).encode()).hexdigest()[:16]
    graded = [r for r in results if not r.grade.skipped]
    passed = [r for r in graded if r.grade.passed]

    return RunRecord(
        run_id=uuid.uuid4().hex[:22],
        target=f"manual:{name}",
        target_version=transcript.get("target_version", ""),
        model="",                            # naməlum — vidcet modeli demir
        dataset_hash=digest,
        started_at=str(transcript.get("tested_at", "")),
        results=results,
        totals={
            "source": "manual_transcript",
            "n_cases": len(selected),
            "n_graded": len(graded),
            "n_passed": len(passed),
            "n_failed": len(graded) - len(passed),
            "n_skipped": len(results) - len(graded),
            "cost_usd": None,
            "measured": {k: False for k in UNMEASURABLE},
            "collected_by": transcript.get("tester", ""),
            "demo_url": transcript.get("demo_url", ""),
            "note": transcript.get("note", ""),
            "warning": (
                "ƏL İLƏ TOPLANMIŞ TRANSKRIPT. Sorğuları insan göndərib; "
                "xərc, gecikmə, retrieval və tool izi ÖLÇÜLMƏYİB (sıfır deyil, "
                "naməlum). Bu artefakt avtomatik qaçışla müqayisə edilə bilməz."
            ),
        },
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("transcript")
    p.add_argument("--dataset", default="evals/datasets/full.jsonl")
    p.add_argument("--out", default=None, help="reports/<run_id>/ qovluğu")
    args = p.parse_args(argv)

    transcript = read_transcript(pathlib.Path(args.transcript))
    cases = load_cases(pathlib.Path(args.dataset))
    record = build(transcript, cases)

    out = pathlib.Path(args.out) if args.out else pathlib.Path("reports") / record.run_id
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{record.run_id}.json"
    path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n")

    t = record.totals
    print(f"{path}")
    print(f"  mənbə   : ƏL İLƏ TRANSKRIPT ({record.target})")
    print(f"  case    : {t['n_cases']} · cavab {len(record.results)}")
    print(f"  keçdi   : {t['n_passed']} · sındı {t['n_failed']} · skipped {t['n_skipped']}")
    print("  xərc    : ÖLÇÜLMƏDİ (naməlum, sıfır deyil)")
    print(f"\n  növbəti : python3 evals/reproduce.py {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Audit əməyinin saat qeydiyyatı — qiymət döşəməsini təxmindən çıxarmaq üçün.

`docs/AUDIT-COST.md` §10 qiymət döşəməsini rəqəmlə deyil, **düsturla** verir:

    döşəmə = model xərci + H × R

Model xərci ölçülüb ($20–26 tipik audit üçün, §11). `R` biznes qərarıdır.
Ölçülməyən yeganə şey **H** — təkrarlanan mərhələlərin saatıdır, və o
naməlum qaldıqca hər qiymət təxmindir.

Bu modul H-i ölçür. Mərhələ adları §9-dakı «HƏR MÜŞTƏRİDƏ» sətirlərinin
eynisidir, yoxsa ölçü sənədlə tutuşmaz.

**Yazılmamış mərhələ sıfır DEYİL — naməlumdur.** Hesabat onu `[N]` kimi
göstərir və heç vaxt cəmə 0 kimi qatmır. Bu, sənədin öz qaydasıdır: «"təxminən"
cavabı qəbuledilməzdir; "$X ölçüldü, N cəhdin xərci ölçülmədi" isə dürüstdür».

    python -m agentproof.timesheet start korpus --engagement acme
    python -m agentproof.timesheet stop --engagement acme
    python -m agentproof.timesheet report --engagement acme --rate 100
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from typing import Any

#: `docs/AUDIT-COST.md` §9 — «HƏR MÜŞTƏRİDƏ» təkrarlanan iş.
#: Ad dəyişsə sənəd də dəyişməlidir; test bunu qoruyur.
STAGES: dict[str, str] = {
    "korpus": "Korpus + ground truth",
    "dataset": "Dataset generasiyası",
    "qacis": "Tam qaçış (×3 təkrar)",
    "triage": "Triage (əl ilə cavab oxuma)",
    "grader-auditi": "Grader auditi",
    "hesabat": "Hesabatın yazılması",
    "kalibrasiya": "Judge kalibrasiyası (rubrika dəyişəndə)",
}

#: §11 — ölçülmüş model xərcinin ALT HƏDDİ, tipik audit üçün.
MODEL_COST_FLOOR_USD = 20.17
MODEL_COST_CEILING_USD = 26.40

DEFAULT_DIR = pathlib.Path("timesheets")


class Timesheet:
    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {"entries": [], "open": None}
        if path.exists():
            self.data = json.loads(path.read_text())

    # ------------------------------------------------------------ yazma
    def start(self, stage: str, note: str = "") -> str:
        if stage not in STAGES:
            raise ValueError(
                f"naməlum mərhələ: {stage!r}\n  mövcud: {', '.join(STAGES)}"
            )
        if self.data["open"] is not None:
            open_stage = self.data["open"]["stage"]
            raise ValueError(
                f"{open_stage!r} hələ açıqdır — əvvəlcə `stop` et. "
                "Eyni anda iki mərhələ saymaq saatı ikiqat yazardı."
            )
        self.data["open"] = {"stage": stage, "at": time.time(), "note": note}
        self._save()
        return STAGES[stage]

    def stop(self) -> tuple[str, float]:
        if self.data["open"] is None:
            raise ValueError("açıq mərhələ yoxdur")
        entry = self.data.pop("open")
        self.data["open"] = None
        hours = (time.time() - entry["at"]) / 3600
        self.data["entries"].append(
            {
                "stage": entry["stage"],
                "hours": round(hours, 4),
                "note": entry.get("note", ""),
                "ended": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        )
        self._save()
        return entry["stage"], hours

    def add(self, stage: str, hours: float, note: str = "") -> None:
        """Keçmiş işi əl ilə yaz — sayğac unudulanda."""
        if stage not in STAGES:
            raise ValueError(f"naməlum mərhələ: {stage!r}")
        if hours <= 0:
            raise ValueError("saat müsbət olmalıdır")
        self.data["entries"].append(
            {
                "stage": stage,
                "hours": round(hours, 4),
                "note": note,
                "ended": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "manual": True,
            }
        )
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n")

    # ------------------------------------------------------------ oxuma
    def by_stage(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for e in self.data["entries"]:
            out[e["stage"]] = out.get(e["stage"], 0.0) + e["hours"]
        return out

    def unmeasured(self) -> list[str]:
        """Heç bir qeydi olmayan mərhələlər — sıfır deyil, NAMƏLUM."""
        recorded = self.by_stage()
        return [s for s in STAGES if s not in recorded and s != "kalibrasiya"]

    def report(self, rate: float | None = None) -> str:
        measured = self.by_stage()
        missing = self.unmeasured()
        total = sum(measured.values())

        lines = [f"TIMESHEET · {self.path}", ""]
        lines.append(f"{'mərhələ':<16}{'saat':>8}  status")
        lines.append("-" * 56)
        for key, label in STAGES.items():
            if key in measured:
                lines.append(f"{key:<16}{measured[key]:>8.2f}  [Ö] ölçüldü — {label}")
            elif key == "kalibrasiya":
                lines.append(f"{key:<16}{'—':>8}  [⊘] rubrika dəyişməyib — {label}")
            else:
                lines.append(f"{key:<16}{'?':>8}  [N] NAMƏLUM — {label}")
        lines.append("-" * 56)
        lines.append(f"{'ölçülən cəm':<16}{total:>8.2f}  saat")

        if missing:
            lines += [
                "",
                f"⚠️  {len(missing)} təkrarlanan mərhələ ölçülməyib: {', '.join(missing)}",
                "    Cəm TAM DEYİL. Bu rəqəmdən qiymət çıxarmaq təxmin etməkdir.",
            ]

        if rate is not None:
            labour_lo = total * rate
            floor_lo = MODEL_COST_FLOOR_USD + labour_lo
            floor_hi = MODEL_COST_CEILING_USD + labour_lo
            lines += [
                "",
                f"Saatlıq dərəcə R = ${rate:,.0f}",
                f"Əmək (ölçülən H)  = ${labour_lo:,.0f}",
                f"Model xərci       = ${MODEL_COST_FLOOR_USD:.2f}–{MODEL_COST_CEILING_USD:.2f}  [Ö]",
                f"DÖŞƏMƏ            = ${floor_lo:,.0f}–{floor_hi:,.0f}"
                + ("  ⚠️ ALT HƏDD — ölçülməyən mərhələlər var" if missing else ""),
            ]
        return "\n".join(lines)


# ------------------------------------------------------------------- CLI
def _sheet(engagement: str, directory: str | None) -> Timesheet:
    base = pathlib.Path(directory) if directory else DEFAULT_DIR
    return Timesheet(base / f"{engagement}.json")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agentproof.timesheet", description=__doc__)
    p.add_argument("--engagement", required=True, help="müştəri / audit adı")
    p.add_argument("--dir", default=None, help=f"qovluq (defolt: {DEFAULT_DIR})")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start"); s.add_argument("stage"); s.add_argument("--note", default="")
    sub.add_parser("stop")
    a = sub.add_parser("add"); a.add_argument("stage"); a.add_argument("hours", type=float)
    a.add_argument("--note", default="")
    sub.add_parser("status")
    r = sub.add_parser("report"); r.add_argument("--rate", type=float, default=None)

    args = p.parse_args(argv)
    sheet = _sheet(args.engagement, args.dir)

    try:
        if args.cmd == "start":
            print(f"başladı: {sheet.start(args.stage, args.note)}")
        elif args.cmd == "stop":
            stage, hours = sheet.stop()
            print(f"bitdi: {STAGES[stage]} · {hours:.2f} saat")
        elif args.cmd == "add":
            sheet.add(args.stage, args.hours, args.note)
            print(f"yazıldı: {STAGES[args.stage]} · {args.hours:.2f} saat")
        elif args.cmd == "status":
            open_ = sheet.data["open"]
            if open_ is None:
                print("açıq mərhələ yoxdur")
            else:
                mins = (time.time() - open_["at"]) / 60
                print(f"açıq: {STAGES[open_['stage']]} · {mins:.0f} dəqiqədir")
        elif args.cmd == "report":
            print(sheet.report(args.rate))
    except ValueError as e:
        print(f"XƏTA: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

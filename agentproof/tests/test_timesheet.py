"""Saat qeydiyyatı ölçülməyəni sıfır kimi göstərmir (AP-062).

Bu modulun bütün dəyəri bir qaydadadır: **yazılmamış mərhələ sıfır deyil,
naməlumdur.** Onu 0 saymaq döşəməni süni şəkildə aşağı salır və qiyməti
«ölçülmüş» kimi göstərir — halbuki o, yenə təxmindir.
"""

from __future__ import annotations

import json

import pytest

from agentproof.timesheet import STAGES, Timesheet, main


def _sheet(tmp_path):
    return Timesheet(tmp_path / "acme.json")


def test_stage_names_match_the_cost_document(tmp_path) -> None:
    """Mərhələ adları AUDIT-COST.md §9 ilə eynidir — yoxsa ölçü tutuşmaz."""
    doc = (tmp_path / "..").resolve()  # yalnız oxunaqlıq üçün
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "docs" / "AUDIT-COST.md").read_text()
    for label in STAGES.values():
        head = label.split(" (")[0]
        assert head in text, f"§9-da yoxdur: {head}"
    assert doc  # susdurucu


def test_unmeasured_stage_is_unknown_never_zero(tmp_path) -> None:
    sheet = _sheet(tmp_path)
    sheet.add("triage", 2.0)

    out = sheet.report(rate=100)

    assert "[N] NAMƏLUM" in out
    assert "korpus" in sheet.unmeasured()
    assert "ölçülməyən mərhələlər var" in out
    # Cəm YALNIZ ölçüləni tutur — naməlumlar 0 kimi qatılmır.
    assert "2.00" in out


def test_floor_is_marked_as_a_lower_bound_while_stages_are_missing(tmp_path) -> None:
    sheet = _sheet(tmp_path)
    sheet.add("triage", 3.0)
    assert "ALT HƏDD" in sheet.report(rate=150)


def test_floor_loses_the_warning_once_every_stage_is_measured(tmp_path) -> None:
    sheet = _sheet(tmp_path)
    for stage in STAGES:
        if stage != "kalibrasiya":
            sheet.add(stage, 1.0)
    out = sheet.report(rate=100)
    assert "ALT HƏDD" not in out
    assert "NAMƏLUM" not in out


def test_two_stages_cannot_run_at_once(tmp_path) -> None:
    sheet = _sheet(tmp_path)
    sheet.start("korpus")
    with pytest.raises(ValueError, match="hələ açıqdır"):
        sheet.start("triage")


def test_unknown_stage_is_refused(tmp_path) -> None:
    sheet = _sheet(tmp_path)
    with pytest.raises(ValueError, match="naməlum mərhələ"):
        sheet.start("yeni-merhele")


def test_hours_accumulate_across_entries(tmp_path) -> None:
    sheet = _sheet(tmp_path)
    sheet.add("qacis", 1.5)
    sheet.add("qacis", 0.5)
    assert sheet.by_stage()["qacis"] == 2.0


def test_state_survives_a_new_process(tmp_path) -> None:
    _sheet(tmp_path).add("hesabat", 4.0)
    assert Timesheet(tmp_path / "acme.json").by_stage() == {"hesabat": 4.0}
    stored = json.loads((tmp_path / "acme.json").read_text())
    assert stored["entries"][0]["stage"] == "hesabat"


def test_cli_round_trip(tmp_path, capsys) -> None:
    argv = ["--engagement", "acme", "--dir", str(tmp_path)]
    assert main(argv + ["add", "triage", "2.5"]) == 0
    assert main(argv + ["report", "--rate", "100"]) == 0
    out = capsys.readouterr().out
    assert "DÖŞƏMƏ" in out and "[N] NAMƏLUM" in out


def test_cli_reports_a_bad_stage_instead_of_writing_it(tmp_path, capsys) -> None:
    argv = ["--engagement", "acme", "--dir", str(tmp_path)]
    assert main(argv + ["add", "uydurma", "1"]) == 2
    assert "naməlum mərhələ" in capsys.readouterr().err
    assert not (tmp_path / "acme.json").exists()

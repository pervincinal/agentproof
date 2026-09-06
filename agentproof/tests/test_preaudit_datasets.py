"""Ön-audit datasetləri hədəfin çat pəncərəsinə SIĞMALIDIR.

NİYƏ VAR. Acorn-un çatı mesaj başına 140 simvol qəbul edir. Bir sual 142
simvol idi və bunu yalnız Parvin çatı açandan sonra görəcəkdi — işin
ortasında, sualı kəsməklə. Kəsilmiş sual isə **başqa şey ölçür**: şərtlərdən
biri düşür (məsələn «no claims») və cavab artıq tələni sınamır.

Hədd datasetin başında maşın oxunan direktivdir:

    //! max_input_chars = 140

Direktiv yoxdursa yoxlama tətbiq olunmur — hər çat eyni deyil.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PREAUDIT = ROOT / "evals" / "datasets" / "preaudit"
DIRECTIVE = re.compile(r"^//!\s*max_input_chars\s*=\s*(\d+)\s*$")

DATASETS = sorted(PREAUDIT.glob("*.jsonl"))


def _load(path: pathlib.Path) -> tuple[list[dict], int | None]:
    cases, limit = [], None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        m = DIRECTIVE.match(line)
        if m:
            limit = int(m.group(1))
            continue
        if line.startswith("//"):
            continue
        cases.append(json.loads(line))
    return cases, limit


def test_there_is_at_least_one_preaudit_dataset() -> None:
    assert DATASETS, "preaudit/ boşdur — bu test mənasız keçərdi"


@pytest.mark.parametrize("path", DATASETS, ids=lambda p: p.stem)
def test_every_question_fits_the_chat_window(path: pathlib.Path) -> None:
    cases, limit = _load(path)
    if limit is None:
        pytest.skip(f"{path.name}: simvol həddi elan olunmayıb")
    over = [(c["id"], len(c["input"])) for c in cases if len(c["input"]) > limit]
    assert not over, (
        f"{path.name}: {limit} simvol həddini aşan sual(lar): "
        + ", ".join(f"{cid} ({n})" for cid, n in over)
    )


@pytest.mark.parametrize("path", DATASETS, ids=lambda p: p.stem)
def test_every_case_explains_its_ground_truth(path: pathlib.Path) -> None:
    """`note` olmadan dataset bir ay sonra oxunmur — və mənbəsi yoxlanmır."""
    cases, _ = _load(path)
    missing = [c["id"] for c in cases if not c.get("note", "").strip()]
    assert not missing, f"{path.name}: `note` yoxdur: {missing}"


@pytest.mark.parametrize("path", DATASETS, ids=lambda p: p.stem)
def test_case_ids_are_unique(path: pathlib.Path) -> None:
    cases, _ = _load(path)
    ids = [c["id"] for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"{path.name}: təkrarlanan id: {sorted(dupes)}"


@pytest.mark.parametrize("path", DATASETS, ids=lambda p: p.stem)
def test_graders_are_registered(path: pathlib.Path) -> None:
    from agentproof.graders import registry

    cases, _ = _load(path)
    for c in cases:
        registry.get(c["grader"])

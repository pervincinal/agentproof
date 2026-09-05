"""İzləmə siyahısı ilə ictimai səhifə eyni şeyi deməlidir (AP-069).

`site/independence.html` səkkiz satınalmanı sadalayır və həmin siyahı bizim
müstəqillik arqumentimizin dəlil bazasıdır. Doqquzuncusu baş verib səhifədə
yoxdursa, səhifə səhvdir — və o səhifənin bütün mənası dəqiqliyindədir.

Bu test ikisinin ayrılmasını bloklayır.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
WATCH = ROOT / "docs" / "COMPETITOR-WATCH.md"
PAGE = ROOT / "site" / "independence.html"

#: Sənəddə və səhifədə eyni yazılmalı olan adlar.
ACQUISITIONS = {
    "Weights": "CoreWeave",
    "Velvet": "Arize",
    "Humanloop": "Anthropic",
    "Statsig": "OpenAI",
    "Langfuse": "ClickHouse",
    "Promptfoo": "OpenAI",
    "Helicone": "Mintlify",
    "Galileo": "Cisco",
}


def test_every_recorded_acquisition_appears_on_the_public_page() -> None:
    page = PAGE.read_text()
    for target, buyer in ACQUISITIONS.items():
        assert target in page, f"səhifədə yoxdur: {target}"
        assert buyer in page, f"səhifədə alıcı yoxdur: {buyer}"


def test_watch_document_records_the_same_set() -> None:
    watch = WATCH.read_text()
    for target in ACQUISITIONS:
        assert target in watch, f"izləmə sənədində yoxdur: {target}"


def test_page_does_not_list_more_acquisitions_than_we_track() -> None:
    """Səhifəyə sətir əlavə olunub izləməyə əlavə olunmayıbsa, tutulsun."""
    page = PAGE.read_text()
    rows = re.findall(r'<tr><td class="k">(.*?)</td>', page)
    assert len(rows) == len(ACQUISITIONS), (
        f"səhifədə {len(rows)} sətir, izlədiyimiz {len(ACQUISITIONS)} — "
        "biri digərindən ayrılıb"
    )


def test_next_check_date_is_recorded() -> None:
    """«Yoxlanılmadı» ilə «dəyişməyib» fərqli şeylərdir."""
    watch = WATCH.read_text()
    assert re.search(r"NÖVBƏTİ YOXLAMA: \d{4}-\d{2}-\d{2}", watch)
    assert re.search(r"\*\*Son yoxlama:\*\* \d{4}-\d{2}-\d{2}", watch)

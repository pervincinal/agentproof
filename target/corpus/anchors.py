#!/usr/bin/env python
"""Retrieval gold lövbərləri: `doc#clause` → Dify segment id xəritəsi.

PROBLEM. Pilot dataset-də gold chunk-lar birbaşa Dify segment UUID-ləri idi
(`5d00bd2a-1ed2-...`). Bilik bazası yenidən indeksləndikdə Dify BÜTÜN segment
id-lərini yenidən yaradır — yəni hər retrieval case-i səssizcə sınır və
uğursuzluq "retrieval pisləşdi" kimi görünür, halbuki heç nə pisləşməyib.

HƏLL. Dataset-də YALNIZ sabit, insan tərəfindən oxuna bilən lövbərlər saxlanır:

    "gold_chunks": ["returns-and-refunds.md#2.1"]

Qaçışdan əvvəl bu modul dataset API-dən segmentləri çəkir, hər segmentin
İÇİNDƏKİ bənd nömrələrini parse edir və `doc#clause → segment_id` xəritəsini
`target/corpus/anchor-map.json`-a yazır. `resolve_cases()` qaçış zamanı
lövbərləri segment id-lərinə çevirir.

POZULMAZ QAYDA — SƏSSİZ KEÇMƏ YOXDUR.
  * xəritə faylı yoxdursa           → AnchorMapMissing
  * lövbər xəritədə yoxdursa        → AnchorResolutionError
  * xəritə köhnəlibsə (`verify`)    → AnchorMapStale
Heç bir halda case sükutla "gold chunk yoxdur" vəziyyətinə düşmür.

İstifadə:
    python target/corpus/anchors.py build      # canlı KB-dən xəritə qur
    python target/corpus/anchors.py verify     # xəritə hələ də düzgündürmü
    python target/corpus/anchors.py show returns-and-refunds.md

Açarlar mühitdən və ya `~/agentproof-stack/dify/docker/.env`-dən oxunur:
`AGENTPROOF_DATASET_KEY`, `AGENTPROOF_DATASET_ID`, `DIFY_BASE_URL`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

CORPUS_DIR = Path(__file__).resolve().parent
DEFAULT_MAP_PATH = CORPUS_DIR / "anchor-map.json"
DEFAULT_ENV_FILE = Path.home() / "agentproof-stack" / "dify" / "docker" / ".env"
DEFAULT_BASE_URL = "http://localhost:8088/v1"

SCHEMA_VERSION = 1

# `returns-and-refunds.md#2.1` — dataset-dəki lövbər sintaksisi.
# Qəsdən DARDIR: `.md` tələb olunur, ona görə köhnə/mock dataset-lərdəki
# `returns-and-refunds#window` kimi sətirlər lövbər sayılmır və toxunulmur.
ANCHOR_RE = re.compile(r"^(?P<doc>[A-Za-z0-9._-]+\.md)#(?P<clause>[A-Za-z0-9.\-]+)$")

# Segment məzmunundan bənd açarlarının çıxarılması.
_CLAUSE_RE = re.compile(r"^(?P<n>\d+)\.(?P<m>\d+)\b")          # "2.1 The standard ..."
_SECTION_RE = re.compile(r"^(?P<n>\d+)\.\s+\S")                # "2. Standard return window"
_APPENDIX_RE = re.compile(r"^Appendix\s+([A-Z])\b", re.IGNORECASE)
_APPENDIX_CLAUSE_RE = re.compile(r"^([A-Z])\.(\d+)\b")         # "A.1 The standard return window..."


class AnchorError(RuntimeError):
    """Lövbər qatının bütün xətalarının kökü — heç biri sükutla udulmur."""


class AnchorMapMissing(AnchorError):
    pass


class AnchorResolutionError(AnchorError):
    pass


class AnchorMapStale(AnchorError):
    pass


# --------------------------------------------------------------------- xəritə
@dataclass(frozen=True)
class AnchorEntry:
    anchor: str
    segment_id: str
    document_id: str
    document_name: str
    position: int
    content_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor": self.anchor,
            "segment_id": self.segment_id,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "position": self.position,
            "content_sha256": self.content_sha256,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "AnchorEntry":
        return AnchorEntry(
            anchor=d["anchor"],
            segment_id=d["segment_id"],
            document_id=d["document_id"],
            document_name=d["document_name"],
            position=int(d["position"]),
            content_sha256=d["content_sha256"],
        )


@dataclass
class AnchorMap:
    dataset_id: str
    base_url: str
    built_at: str
    entries: dict[str, AnchorEntry] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    # -- I/O ---------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "base_url": self.base_url,
            "built_at": self.built_at,
            "n_anchors": len(self.entries),
            "anchors": {k: v.to_dict() for k, v in sorted(self.entries.items())},
        }

    def save(self, path: Path = DEFAULT_MAP_PATH) -> Path:
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return path

    @staticmethod
    def load(path: Path = DEFAULT_MAP_PATH) -> "AnchorMap":
        if not path.exists():
            raise AnchorMapMissing(
                f"lövbər xəritəsi yoxdur: {path}\n"
                "  Qur: python target/corpus/anchors.py build\n"
                "  (Retrieval case-ləri `doc#clause` lövbərləri ilə yazılıb; xəritə "
                "olmadan onlar segment id-yə çevrilə bilmir və qaçış SƏSSİZ yalan "
                "nəticə verərdi.)"
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        if int(raw.get("schema_version", 0)) != SCHEMA_VERSION:
            raise AnchorMapStale(
                f"{path}: schema_version {raw.get('schema_version')} != {SCHEMA_VERSION} — "
                "xəritəni yenidən qurun"
            )
        return AnchorMap(
            dataset_id=raw["dataset_id"],
            base_url=raw.get("base_url", ""),
            built_at=raw.get("built_at", ""),
            entries={k: AnchorEntry.from_dict(v) for k, v in raw["anchors"].items()},
            schema_version=int(raw["schema_version"]),
        )

    # -- həll --------------------------------------------------------------
    def resolve(self, anchor: str) -> str:
        entry = self.entries.get(anchor)
        if entry is None:
            near = sorted(a for a in self.entries if a.split("#")[0] == anchor.split("#")[0])
            raise AnchorResolutionError(
                f"lövbər xəritədə yoxdur: {anchor!r}\n"
                f"  Bu sənəddə mövcud lövbərlər: {near or '(sənəd tapılmadı)'}\n"
                "  Ya dataset-dəki lövbər səhvdir, ya da xəritə köhnədir "
                "(python target/corpus/anchors.py build)."
            )
        return entry.segment_id


def is_anchor(value: str) -> bool:
    return bool(ANCHOR_RE.match(value))


# --------------------------------------------------------- parse: segment → lövbərlər
def clause_keys(content: str) -> list[str]:
    """Bir segmentin içindəki bənd açarları (sıra: mətndəki görünmə sırası)."""
    keys: list[str] = []
    appendix_letter: str | None = None
    for raw_line in content.splitlines():
        line = raw_line.strip().lstrip("#").strip()
        if not line:
            continue
        line = line.replace("**", "")

        m = _APPENDIX_RE.match(line)
        if m:
            appendix_letter = m.group(1).upper()
            keys.append(f"appendix-{appendix_letter.lower()}")
            continue

        m = _APPENDIX_CLAUSE_RE.match(line)
        if m and appendix_letter is not None and m.group(1).upper() == appendix_letter:
            keys.append(f"appendix-{m.group(1).lower()}.{m.group(2)}")
            continue

        m = _CLAUSE_RE.match(line)
        if m:
            keys.append(f"{m.group('n')}.{m.group('m')}")
            keys.append(m.group("n"))  # bənd varsa bölmə də bu segmentdədir
            continue

        m = _SECTION_RE.match(line)
        if m:
            keys.append(m.group("n"))
    # sıranı qoruyaraq təkrarları at
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def build_entries(documents: list[dict[str, Any]]) -> tuple[dict[str, AnchorEntry], list[str]]:
    """`documents`: [{id, name, segments:[{id, position, content}]}] → xəritə + toqquşmalar."""
    entries: dict[str, AnchorEntry] = {}
    collisions: list[str] = []
    for doc in documents:
        doc_name = doc["name"]
        for seg in sorted(doc["segments"], key=lambda s: int(s.get("position", 0))):
            content = seg.get("content", "") or ""
            sha = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
            for key in clause_keys(content):
                anchor = f"{doc_name}#{key}"
                if anchor in entries:
                    # İlk (ən aşağı position) segment qalır — bölmə başlığı orada olur.
                    collisions.append(
                        f"{anchor}: position {entries[anchor].position} saxlanıldı, "
                        f"{seg.get('position')} atıldı"
                    )
                    continue
                entries[anchor] = AnchorEntry(
                    anchor=anchor,
                    segment_id=str(seg["id"]),
                    document_id=str(doc["id"]),
                    document_name=doc_name,
                    position=int(seg.get("position", 0)),
                    content_sha256=sha,
                )
    return entries, collisions


# ------------------------------------------------------------------ Dify API
def load_env(env_file: Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    """Mühit > .env faylı. Açar heç vaxt loga/çıxışa yazılmır."""
    values: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    for key in ("AGENTPROOF_DATASET_KEY", "AGENTPROOF_DATASET_ID", "DIFY_BASE_URL"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def fetch_documents(base_url: str, api_key: str, dataset_id: str) -> list[dict[str, Any]]:
    """Dataset API-dən bütün sənədləri və onların segmentlərini çəkir."""
    import httpx  # yalnız `build`/`verify` üçün — modul import-u şəbəkəsizdir

    headers = {"Authorization": f"Bearer {api_key}"}
    base = base_url.rstrip("/")
    out: list[dict[str, Any]] = []
    with httpx.Client(timeout=60.0) as client:
        page = 1
        while True:
            r = client.get(
                f"{base}/datasets/{dataset_id}/documents",
                headers=headers,
                params={"page": page, "limit": 100},
            )
            r.raise_for_status()
            body = r.json()
            docs = body.get("data", [])
            if not docs:
                break
            for doc in docs:
                if doc.get("indexing_status") != "completed" or not doc.get("enabled", True):
                    raise AnchorError(
                        f"sənəd indekslənməyib və ya söndürülüb: {doc.get('name')} "
                        f"(status={doc.get('indexing_status')}, enabled={doc.get('enabled')}) — "
                        "yarımçıq indeksdən lövbər xəritəsi qurulmur"
                    )
                segments = _fetch_segments(client, base, headers, dataset_id, str(doc["id"]))
                out.append({"id": doc["id"], "name": doc["name"], "segments": segments})
            if not body.get("has_more"):
                break
            page += 1
    if not out:
        raise AnchorError(f"dataset {dataset_id} boşdur — lövbər xəritəsi qurula bilmir")
    return out


def _fetch_segments(
    client: Any, base: str, headers: dict[str, str], dataset_id: str, doc_id: str
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    page = 1
    while True:
        r = client.get(
            f"{base}/datasets/{dataset_id}/documents/{doc_id}/segments",
            headers=headers,
            params={"page": page, "limit": 100},
        )
        r.raise_for_status()
        body = r.json()
        batch = body.get("data", [])
        segments.extend(
            {"id": s["id"], "position": s.get("position", 0), "content": s.get("content", "")}
            for s in batch
            if s.get("enabled", True)
        )
        if not body.get("has_more"):
            break
        page += 1
    if not segments:
        raise AnchorError(f"sənəd {doc_id} üçün segment yoxdur")
    return segments


def build_map(
    base_url: str | None = None,
    api_key: str | None = None,
    dataset_id: str | None = None,
    env_file: Path = DEFAULT_ENV_FILE,
) -> tuple[AnchorMap, list[str]]:
    from datetime import datetime, timezone

    env = load_env(env_file)
    base_url = base_url or env.get("DIFY_BASE_URL") or DEFAULT_BASE_URL
    api_key = api_key or env.get("AGENTPROOF_DATASET_KEY", "")
    dataset_id = dataset_id or env.get("AGENTPROOF_DATASET_ID", "")
    if not api_key or not dataset_id:
        raise AnchorError(
            "AGENTPROOF_DATASET_KEY / AGENTPROOF_DATASET_ID tapılmadı "
            f"(mühit və ya {env_file})"
        )
    docs = fetch_documents(base_url, api_key, dataset_id)
    entries, collisions = build_entries(docs)
    amap = AnchorMap(
        dataset_id=dataset_id,
        base_url=base_url,
        built_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        entries=entries,
    )
    return amap, collisions


def verify_map(
    path: Path = DEFAULT_MAP_PATH, env_file: Path = DEFAULT_ENV_FILE
) -> list[str]:
    """Saxlanmış xəritəni canlı KB ilə tutuşdurur. Fərqləri qaytarır (boş = təmiz)."""
    stored = AnchorMap.load(path)
    live, _ = build_map(env_file=env_file)
    problems: list[str] = []
    if stored.dataset_id != live.dataset_id:
        problems.append(f"dataset id dəyişib: {stored.dataset_id} → {live.dataset_id}")
    for anchor, entry in sorted(stored.entries.items()):
        current = live.entries.get(anchor)
        if current is None:
            problems.append(f"{anchor}: lövbər artıq mövcud deyil")
        elif current.segment_id != entry.segment_id:
            problems.append(
                f"{anchor}: segment id dəyişib "
                f"({entry.segment_id[:8]} → {current.segment_id[:8]}) — yenidən indekslənib"
            )
        elif current.content_sha256 != entry.content_sha256:
            problems.append(f"{anchor}: segment MƏTNİ dəyişib (sha {entry.content_sha256[:8]})")
    for anchor in sorted(set(live.entries) - set(stored.entries)):
        problems.append(f"{anchor}: yeni lövbər (xəritədə yoxdur)")
    return problems


# ------------------------------------------------------- dataset ilə inteqrasiya
def anchors_in(expect: dict[str, Any]) -> list[str]:
    return [str(g) for g in expect.get("gold_chunks", []) if is_anchor(str(g))]


def resolve_expect(expect: dict[str, Any], amap: AnchorMap) -> dict[str, Any]:
    """`expect.gold_chunks` içindəki lövbərləri segment id-lərinə çevirir.

    Lövbər olmayan dəyərlər (xam UUID və s.) toxunulmadan keçir.
    """
    gold = expect.get("gold_chunks")
    if not gold:
        return expect
    resolved = [amap.resolve(str(g)) if is_anchor(str(g)) else str(g) for g in gold]
    out = dict(expect)
    out["gold_chunks"] = resolved
    out["_gold_anchors"] = [str(g) for g in gold]  # hesabatda izlənə bilsin
    return out


def resolve_cases(cases: Iterable[Any], path: Path = DEFAULT_MAP_PATH) -> list[Any]:
    """`Case` obyektlərinin lövbərlərini yerində həll edir (dataclass frozen → replace).

    Lövbər OLMAYAN dataset üçün heç nə etmir və xəritə faylını da tələb etmir.
    """
    from dataclasses import replace

    cases = list(cases)
    needs = [c for c in cases if anchors_in(getattr(c, "expect", {}) or {})]
    if not needs:
        return cases
    amap = AnchorMap.load(path)
    out: list[Any] = []
    for case in cases:
        if anchors_in(case.expect):
            out.append(replace(case, expect=resolve_expect(case.expect, amap)))
        else:
            out.append(case)
    return out


# ----------------------------------------------------------------------- CLI
def _cmd_build(argv: list[str]) -> int:
    amap, collisions = build_map()
    path = amap.save(Path(argv[0]) if argv else DEFAULT_MAP_PATH)
    docs = sorted({e.document_name for e in amap.entries.values()})
    print(f"Lövbər xəritəsi quruldu: {path}")
    print(f"  dataset : {amap.dataset_id}")
    print(f"  sənəd   : {len(docs)}")
    print(f"  segment : {len({e.segment_id for e in amap.entries.values()})}")
    print(f"  lövbər  : {len(amap.entries)}")
    if collisions:
        print(f"  toqquşma: {len(collisions)} (ilk segment saxlanıldı)")
        for c in collisions[:5]:
            print(f"    - {c}")
    return 0


def _cmd_verify(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else DEFAULT_MAP_PATH
    problems = verify_map(path)
    if problems:
        print(f"XƏRİTƏ KÖHNƏLİB — {len(problems)} fərq:", file=sys.stderr)
        for p in problems[:20]:
            print(f"  - {p}", file=sys.stderr)
        print("\n  Düzəliş: python target/corpus/anchors.py build", file=sys.stderr)
        return 1
    stored = AnchorMap.load(path)
    print(f"Xəritə təmizdir: {len(stored.entries)} lövbər, dataset {stored.dataset_id}")
    return 0


def _cmd_show(argv: list[str]) -> int:
    amap = AnchorMap.load()
    doc = argv[0] if argv else None
    for anchor, entry in sorted(amap.entries.items(), key=lambda kv: (kv[1].document_name, kv[1].position, kv[0])):
        if doc and entry.document_name != doc:
            continue
        print(f"{anchor:52s} pos={entry.position:<3d} {entry.segment_id}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "build":
            return _cmd_build(rest)
        if cmd == "verify":
            return _cmd_verify(rest)
        if cmd == "show":
            return _cmd_show(rest)
    except AnchorError as exc:
        print(f"XƏTA: {exc}", file=sys.stderr)
        return 2
    print(f"naməlum əmr: {cmd!r} (build | verify | show)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

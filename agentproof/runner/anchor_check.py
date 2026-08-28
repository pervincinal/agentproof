"""Lövbər xəritəsi ↔ CARİ dataset uyğunluğu, qaçışdan ƏVVƏL (AP-022).

HADİSƏ (A-19). `target/corpus/anchor-map.json` köhnə dataset-in
(`e1471e22-…`) segment UUID-lərini saxlayırdı, app isə artıq başqa dataset-ə
(`1623dd7e-…`) bağlı idi. Xəritə formal olaraq etibarlı idi — sxem düzgün,
lövbərlər tam — ona görə heç bir qat etiraz etmədi: `resolve_cases()` gold
lövbərləri MÖVCUD OLMAYAN segment id-lərinə çevirdi, `retrieval_hit_at_k` isə
onları retrieval nəticəsində tapmadı və 2 case `0/3` ilə sındı.

Hesabatda bu **«retrieval işləmir»** kimi görünürdü. Əksi doğru idi: retrieval
gold bəndi 1-ci yerdə qaytarmışdı. Yəni səhv nəticə YAŞIL deyil, QIRMIZI idi —
və məhz buna görə daha təhlükəli: saxta tapıntı hesabata düşür, hədəf haqqında
yalan deyilir və vaxt olmayan problemi axtarmağa gedir.

Xəritə yenidən quruldu, amma MEXANİZM qalırdı: xəritə dataset-ə bağlıdır,
dataset dəyişəndə avtomatik yenilənmir və heç bir yerdə xəbərdarlıq yoxdur.
Bu modul həmin boşluğu bağlayır.

DAVRANIŞ (səssiz keçmə yoxdur, lazımsız blok da yoxdur):

  * xəritənin dataset-i ≠ canlı dataset  -> `AnchorMapMismatch` (qaçış DAYANIR)
  * seçimdə retrieval case-i yoxdur       -> `no-retrieval`, blok YOX
  * canlı dataset id oxunmadı             -> `unverified` + XƏBƏRDARLIQ, blok YOX
    (mock hədəf, Dify-sız CI — bunları bloklamaq yoxlamanı söndürməyə məcbur edərdi)
  * `--skip-anchor-check`                 -> `skipped` + XƏBƏRDARLIQ hesabata düşür

Canlı dataset id-si burada YENİDƏN oxunmur: `retrieval_config.probe_retrieval_config()`
onu artıq avtoritet mənbədən (app-ın öz konfiqurasiyası) gətirir (AP-019). İki
ayrı oxuma iki fərqli cavab verə bilərdi — o isə bu modulun həll etdiyi
problemin eynisidir.

Bu modul `inspect_ai` import ETMİR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

#: Xəritə faylının repo daxilindəki insan üçün oxunan adı (mesajlarda).
MAP_LABEL = "target/corpus/anchor-map.json"


class AnchorMapMismatch(RuntimeError):
    """Xəritə başqa dataset-ə aiddir — qaçış davam etməməlidir."""

    def __init__(self, message: str, check: "AnchorCheck") -> None:
        super().__init__(message)
        self.check = check


@dataclass(frozen=True)
class AnchorCheck:
    """Yoxlamanın nəticəsi — `RunRecord.totals["anchor_check"]`-ə düşür."""

    status: str = "unverified"
    """match | mismatch | no-retrieval | unverified | skipped"""

    map_dataset_id: str = ""
    live_dataset_id: str = ""
    dataset_source: str = ""
    map_path: str = MAP_LABEL
    map_built_at: str = ""
    n_retrieval_cases: int = 0
    n_anchored_cases: int = 0
    detail: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Qaçış davam edə bilərmi (xəbərdarlıqla da olsa)."""
        return self.status != "mismatch"

    @property
    def verified(self) -> bool:
        """Uyğunluq HƏQİQƏTƏN sübut olundumu."""
        return self.status == "match"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "map_dataset_id": self.map_dataset_id,
            "live_dataset_id": self.live_dataset_id,
            "dataset_source": self.dataset_source,
            "map_path": self.map_path,
            "map_built_at": self.map_built_at,
            "n_retrieval_cases": self.n_retrieval_cases,
            "n_anchored_cases": self.n_anchored_cases,
            "detail": self.detail,
            "warnings": list(self.warnings),
        }

    def console_line(self) -> str:
        """`evals/run.py` üçün tək sətirlik xülasə."""
        if self.status == "match":
            return (
                f"Lövbər xəritəsi yoxlandı: dataset {self.live_dataset_id[:8]} "
                f"[{self.dataset_source or '—'}] · {self.n_anchored_cases} lövbərli case"
            )
        if self.status == "no-retrieval":
            return f"Lövbər yoxlaması atlandı: {self.detail}"
        if self.status == "skipped":
            return "XƏBƏRDARLIQ — lövbər yoxlaması --skip-anchor-check ilə keçildi"
        return f"XƏBƏRDARLIQ — lövbər xəritəsi yoxlanmadı: {self.detail or self.status}"


# ------------------------------------------------------------------ seçim
def _expect(case: Any) -> dict[str, Any]:
    return getattr(case, "expect", None) or {}


def retrieval_case_ids(cases: Iterable[Any]) -> list[str]:
    """Gold chunk iddiası olan case-lər — yoxlamanı MƏCBURİ edənlər."""
    return [str(getattr(c, "id", "")) for c in cases if _expect(c).get("gold_chunks")]


def anchored_case_ids(cases: Iterable[Any]) -> list[str]:
    """`doc#clause` lövbəri işlədən case-lər.

    `resolve_cases()` artıq işləyibsə orijinal lövbərlər `_gold_anchors`-da
    saxlanılır; işləməyibsə xam `gold_chunks` içində olur. Hər iki forma
    tanınmalıdır, çünki yoxlama həlldən SONRA çağırılır.
    """
    out: list[str] = []
    for case in cases:
        expect = _expect(case)
        values = list(expect.get("_gold_anchors") or []) or list(expect.get("gold_chunks") or [])
        if any("#" in str(v) and str(v).split("#", 1)[0].endswith(".md") for v in values):
            out.append(str(getattr(case, "id", "")))
    return out


# ----------------------------------------------------------------- yoxlama
def _load_map_dataset_id(map_path: Path | None) -> tuple[str, str, str]:
    """`(dataset_id, built_at, xəta_mətni)` — import/fayl xətası ATMIR."""
    try:
        from target.corpus.anchors import DEFAULT_MAP_PATH, AnchorMap  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover — konfiqurasiya xətası
        return "", "", f"lövbər qatı import olunmadı (target/corpus/anchors.py): {exc}"
    path = Path(map_path) if map_path is not None else Path(DEFAULT_MAP_PATH)
    if not path.exists():
        return "", "", f"lövbər xəritəsi yoxdur: {path}"
    try:
        amap = AnchorMap.load(path)
    except Exception as exc:  # xəritə oxunmadı — yoxlama edilə bilmir
        return "", "", f"{path}: {type(exc).__name__}: {exc}"
    return amap.dataset_id, amap.built_at, ""


def verify_anchor_map(
    cases: Iterable[Any],
    live_dataset_id: str = "",
    dataset_source: str = "",
    map_path: Path | str | None = None,
    skip: bool = False,
) -> AnchorCheck:
    """Xəritə cari dataset-ə uyğundurmu. Uyğunsuzluqda `AnchorMapMismatch` ATIR.

    `skip=True` bloklamır, amma nəticə `skipped` statusu və XƏBƏRDARLIQ ilə
    hesabata düşür — səssiz keçid yoxdur (AP-022 §4).
    """
    cases = list(cases)
    retrieval_ids = retrieval_case_ids(cases)
    anchored_ids = anchored_case_ids(cases)
    live = (live_dataset_id or "").strip()
    path_label = str(map_path) if map_path is not None else MAP_LABEL

    if skip:
        return AnchorCheck(
            status="skipped",
            live_dataset_id=live,
            dataset_source=dataset_source,
            map_path=path_label,
            n_retrieval_cases=len(retrieval_ids),
            n_anchored_cases=len(anchored_ids),
            detail="--skip-anchor-check ilə bilərəkdən keçilib",
            warnings=[
                "lövbər xəritəsi ↔ dataset uyğunluğu `--skip-anchor-check` ilə "
                f"YOXLANMADI — {len(retrieval_ids)} retrieval case-i bayat xəritə "
                "üzündən saxta şəkildə sına bilər (A-19)"
            ],
        )

    if not retrieval_ids:
        # Retrieval iddiası yoxdursa xəritə nəticəyə TƏSİR ETMİR — bloklamaq
        # yalnız harness-i söndürməyə məcbur edərdi.
        return AnchorCheck(
            status="no-retrieval",
            live_dataset_id=live,
            dataset_source=dataset_source,
            map_path=path_label,
            detail="seçilmiş case-lərdə retrieval (gold_chunks) iddiası yoxdur",
        )

    map_dataset_id, built_at, load_error = _load_map_dataset_id(
        Path(map_path) if map_path is not None else None
    )

    if load_error:
        # Lövbərli case varsa bura ümumiyyətlə çatmır: `resolve_cases()` daha
        # əvvəl `AnchorMapMissing` atır. Deməli qalan hal — xam segment id-li
        # gold-lar (köhnə dataset-lər). Onlar da dataset dəyişəndə sınır, ona
        # görə susmaq olmaz.
        return AnchorCheck(
            status="unverified",
            live_dataset_id=live,
            dataset_source=dataset_source,
            map_path=path_label,
            n_retrieval_cases=len(retrieval_ids),
            n_anchored_cases=len(anchored_ids),
            detail=load_error,
            warnings=[
                f"lövbər xəritəsi oxunmadı ({load_error}) — {len(retrieval_ids)} "
                "retrieval case-inin gold chunk-ları cari dataset-ə aid olduğu "
                "SÜBUT EDİLMİR"
            ],
        )

    if not live:
        return AnchorCheck(
            status="unverified",
            map_dataset_id=map_dataset_id,
            dataset_source=dataset_source,
            map_path=path_label,
            map_built_at=built_at,
            n_retrieval_cases=len(retrieval_ids),
            n_anchored_cases=len(anchored_ids),
            detail="canlı dataset id oxunmadı (retrieval yoxlaması `unknown` qaytardı)",
            warnings=[
                f"lövbər xəritəsi dataset {map_dataset_id or '?'}-ə aiddir, hədəfin "
                "CARİ dataset-i isə müəyyən edilmədi — uyğunluq YOXLANMADI. "
                "`--dify-app-id` / `--dataset-id` + `--dataset-api-key` verilsə "
                f"yoxlanardı; {len(retrieval_ids)} retrieval case-i risk altındadır (A-19)"
            ],
        )

    if map_dataset_id != live:
        check = AnchorCheck(
            status="mismatch",
            map_dataset_id=map_dataset_id,
            live_dataset_id=live,
            dataset_source=dataset_source,
            map_path=path_label,
            map_built_at=built_at,
            n_retrieval_cases=len(retrieval_ids),
            n_anchored_cases=len(anchored_ids),
            detail=f"xəritə {map_dataset_id} → canlı {live}",
        )
        sample = ", ".join(retrieval_ids[:5]) + ("…" if len(retrieval_ids) > 5 else "")
        raise AnchorMapMismatch(
            "LÖVBƏR XƏRİTƏSİ BAYATDIR — qaçış dayandırıldı.\n"
            f"  xəritənin dataset-i    : {map_dataset_id or '(boş)'}  ({path_label})\n"
            f"  hədəfin CARİ dataset-i : {live}  [{dataset_source or '?'}]\n"
            f"  xəritə quruldu         : {built_at or '?'}\n"
            f"  təsir altındakı case   : {len(retrieval_ids)} retrieval ({sample})\n"
            "  Xəritə köhnə dataset-in segment id-lərini saxlayır. Gold chunk-lar\n"
            "  mövcud olmayan segmentlərə göstərəcək, case-lər `0/k` ilə sınacaq və\n"
            "  hesabatda bu «retrieval işləmir» SAXTA tapıntısı kimi görünəcək (A-19).\n"
            "  Düzəliş : python target/corpus/anchors.py build\n"
            "  Yoxla   : python target/corpus/anchors.py verify\n"
            "  Bilərəkdən davam: --skip-anchor-check (səbəb hesabata düşür)",
            check,
        )

    return AnchorCheck(
        status="match",
        map_dataset_id=map_dataset_id,
        live_dataset_id=live,
        dataset_source=dataset_source,
        map_path=path_label,
        map_built_at=built_at,
        n_retrieval_cases=len(retrieval_ids),
        n_anchored_cases=len(anchored_ids),
        detail=f"xəritə və hədəf eyni dataset-ə ({live}) baxır",
    )

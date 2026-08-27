"""Retrieval konfiqurasiyasını CANLI sistemdən oxuyur (LIM-E06 / AP-019).

Problem (VALID-03-dən): `RunRecord` embedder adını və faktiki `top_k`-nı
saxlamırdı. Hesabatın iki ən yük daşıyan parametri qaçış artefaktından yox,
KƏNAR sənəddən oxunurdu — və o sənədlər bir-biri ilə ziddiyyətli idi
(DSL `top_k: 4` ↔ canlı ölçmə `top_k=8`). Ziddiyyət yenidən baş verəndə hansı
rəqəmin hansı konfiqurasiyaya aid olduğunu SÜBUT etmək mümkün deyildi.

Ona görə bu modul heç bir sənədə, DSL-ə və ya konfiq faylına baxmır. Ardıcıllıq:

  1. **Hansı dataset?** — avtoritet mənbə app-ın özüdür:
     `apps.app_model_config_id -> app_model_configs.dataset_configs -> datasets[].dataset.id`.
     `AGENTPROOF_DATASET_ID` mühit dəyişəni yalnız EHTİYATDIR və nəticədə
     `dataset_source: "env"` kimi işarələnir — çünki env bayat ola bilər
     (canlı sistemdə məhz belə idi: env köhnə dataset-i göstərirdi, app isə
     başqasına bağlı idi).
  2. **Konfiqurasiya nədir?** — `GET /v1/datasets/{id}` (Dify Knowledge API):
     `embedding_model`, `embedding_model_provider`, `retrieval_model_dict`.

⚠️ `retrieval_model_dict` TƏLƏDİR. Dify onu `retrieval_model or default` kimi
qaytarır: dataset-in `retrieval_model` sütunu NULL olsa da cavabda `top_k: 4`
görünür. Amma agent yolunda faktiki dəyər həmin halda **2**-dir (OPS-03:
`dataset_retrieval.py` lokal defaultu). Yəni API-nin rəqəmi sütun NULL olanda
YANLIŞDIR. Cavabda `retrieval_model` sahəsi ümumiyyətlə yoxdur (OPS-05), ona
görə API-nin ÖZÜ "sabitlənib" ilə "default-a düşüb" arasında fərq qoya bilmir.
Fərqi yalnız baza deyir. Modul sütunu ayrıca yoxlayır və:

  * sütun doludur  -> `status="live"`, `effective_top_k` = API-nin dəyəri
  * sütun NULL-dur -> `status="partial"`, `effective_top_k=None` + XƏBƏRDARLIQ.
    Bilə-bilə yanlış rəqəmi yazmaqdansa "naməlum" yazmaq düzgündür.
  * baza oxunmur   -> `status="partial"`, rəqəm saxlanır, amma TƏSDİQLƏNMƏMİŞ
    kimi işarələnir.

Heç bir yolda SƏSSİZ default yoxdur: oxunmayan hər dəyər açıq `"unknown"` /
`None` qalır və `RunRecord.totals["retrieval_check"]` vasitəsilə hesabatda
görünən xəbərdarlığa çevrilir.

Bu modul `inspect_ai` import ETMİR.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

# `UUID_RE` `sut_model`-dan təkrar istifadə olunur: dəyər sorğuya sətir kimi
# yapışdırılır, ona görə format yoxlaması hər iki modulda EYNİ olmalıdır.
from agentproof.runner.sut_model import UUID_RE
from agentproof.types import UNKNOWN, RunRecord

DEFAULT_DB_CONTAINER = os.environ.get("AGENTPROOF_DIFY_DB_CONTAINER", "docker-db_postgres-1")
DEFAULT_DB_NAME = os.environ.get("AGENTPROOF_DIFY_DB_NAME", "dify")
DEFAULT_DB_USER = os.environ.get("AGENTPROOF_DIFY_DB_USER", "postgres")

#: `sut_model.py`-dakı ilə EYNİ səbəbdən `app_model_config_id` ilə join edilir:
#: `where app_id = ...` app-ın bayat konfiqurasiya sətrini qaytara bilər.
DATASET_CONFIGS_QUERY = (
    "select amc.dataset_configs::text from apps a "
    "join app_model_configs amc on amc.id = a.app_model_config_id "
    "where a.id = '{app_id}';"
)

#: Sütunun ÖZÜ (API onu qaytarmır — OPS-05). Boş sətir = NULL = default-a düşür.
RETRIEVAL_MODEL_QUERY = (
    "select coalesce(retrieval_model::text, '') from datasets where id = '{dataset_id}';"
)

Runner = Callable[[list[str]], str]
Fetcher = Callable[[str, str], dict[str, Any]]


class RetrievalConfigUnavailable(RuntimeError):
    """Canlı mənbə oxunmadı — dəyər UYDURULMUR, `unknown` qalır."""


# ------------------------------------------------------------------ nəticə
@dataclass(frozen=True)
class RetrievalCheck:
    """Canlı oxunuşun nəticəsi — `RunRecord.totals["retrieval_check"]`-ə düşür."""

    status: str = "unavailable"          # live | partial | unavailable | skipped
    dataset_id: str = ""
    dataset_name: str = ""
    dataset_source: str = ""             # app-config | env | given
    embedding_model: str = UNKNOWN
    embedding_provider: str = UNKNOWN
    effective_top_k: int | None = None
    reranking_enabled: bool | None = None
    search_method: str = UNKNOWN
    top_k_pinned: bool | None = None
    """Dataset-in `retrieval_model` sütunu doludurmu. `None` = yoxlanmayıb."""

    api_top_k: int | None = None
    """API-nin verdiyi rəqəm — sütun NULL olanda bu, YANILDICI dəyərdir."""

    detail: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "live"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
            "dataset_source": self.dataset_source,
            "embedding_model": self.embedding_model,
            "embedding_provider": self.embedding_provider,
            "effective_top_k": self.effective_top_k,
            "reranking_enabled": self.reranking_enabled,
            "search_method": self.search_method,
            "top_k_pinned": self.top_k_pinned,
            "api_top_k": self.api_top_k,
            "detail": self.detail,
            "warnings": list(self.warnings),
        }


# --------------------------------------------------------------- baza yolu
def _docker_psql(args: list[str]) -> str:
    if shutil.which("docker") is None:
        raise RetrievalConfigUnavailable("`docker` PATH-da yoxdur")
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        raise RetrievalConfigUnavailable(f"{type(e).__name__}: {e}") from e
    if proc.returncode != 0:
        raise RetrievalConfigUnavailable(
            f"psql exit {proc.returncode}: {(proc.stderr or '').strip()[:200]}"
        )
    return proc.stdout


def _psql(query: str, container: str, db: str, user: str, runner: Runner) -> str:
    return runner(["docker", "exec", container, "psql", "-U", user, "-d", db, "-tAc", query])


def read_app_dataset_ids(
    app_id: str,
    container: str = DEFAULT_DB_CONTAINER,
    db: str = DEFAULT_DB_NAME,
    user: str = DEFAULT_DB_USER,
    runner: Runner = _docker_psql,
) -> list[str]:
    """App-in HAZIRDA bağlı olduğu dataset id-ləri (avtoritet mənbə)."""
    if not UUID_RE.match(app_id or ""):
        raise RetrievalConfigUnavailable(f"app id UUID deyil: {app_id!r}")
    row = (_psql(
        DATASET_CONFIGS_QUERY.format(app_id=app_id), container, db, user, runner
    ) or "").strip()
    if not row:
        raise RetrievalConfigUnavailable(f"app tapılmadı və ya `dataset_configs` boşdur: {app_id}")
    try:
        payload = json.loads(row.splitlines()[0])
    except ValueError as e:
        raise RetrievalConfigUnavailable(f"`dataset_configs` JSON parse olunmadı: {e}") from e
    entries = ((payload or {}).get("datasets") or {}).get("datasets") or []
    ids = [
        str((e.get("dataset") or {}).get("id") or "").strip()
        for e in entries
        if isinstance(e, dict)
    ]
    ids = [i for i in ids if i]
    if not ids:
        raise RetrievalConfigUnavailable(f"app-ə heç bir dataset bağlanmayıb: {app_id}")
    return ids


def read_retrieval_model_column(
    dataset_id: str,
    container: str = DEFAULT_DB_CONTAINER,
    db: str = DEFAULT_DB_NAME,
    user: str = DEFAULT_DB_USER,
    runner: Runner = _docker_psql,
) -> dict[str, Any] | None:
    """Dataset-in `retrieval_model` sütunu. `None` = NULL (default-a düşür)."""
    if not UUID_RE.match(dataset_id or ""):
        raise RetrievalConfigUnavailable(f"dataset id UUID deyil: {dataset_id!r}")
    out = _psql(
        RETRIEVAL_MODEL_QUERY.format(dataset_id=dataset_id), container, db, user, runner
    )
    # BOŞ SƏTİR MƏNALIDIR — ona görə boş sətirlər süzülmür:
    #   çıxış tamamilə boşdur  -> sətir yoxdur (dataset tapılmadı)
    #   çıxış "\n"-dir         -> sətir var, sütun NULL (`coalesce` -> '')
    lines = (out or "").splitlines()
    if not lines:
        raise RetrievalConfigUnavailable(f"dataset tapılmadı: {dataset_id}")
    raw = lines[0].strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError as e:
        raise RetrievalConfigUnavailable(f"`retrieval_model` JSON parse olunmadı: {e}") from e


# ---------------------------------------------------------------- API yolu
def _api_root(base_url: str) -> str:
    """`DIFY_BASE_URL` bəzən `/v1` ilə, bəzən onsuz gəlir — ikisi də işləməlidir."""
    root = (base_url or "http://localhost:8088").rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return root


def _http_fetch(url: str, api_key: str) -> dict[str, Any]:
    try:
        response = httpx.get(
            url, headers={"Authorization": f"Bearer {api_key}"}, timeout=15.0
        )
    except httpx.HTTPError as e:
        raise RetrievalConfigUnavailable(f"{type(e).__name__}: {e}") from e
    if response.status_code != 200:
        raise RetrievalConfigUnavailable(
            f"HTTP {response.status_code}: {response.text[:200]}"
        )
    try:
        payload = response.json()
    except ValueError as e:
        raise RetrievalConfigUnavailable(f"cavab JSON deyil: {e}") from e
    if not isinstance(payload, dict):
        raise RetrievalConfigUnavailable("cavab JSON obyekti deyil")
    return payload


def fetch_dataset(
    dataset_id: str,
    base_url: str,
    api_key: str,
    fetcher: Fetcher = _http_fetch,
) -> dict[str, Any]:
    """`GET /v1/datasets/{id}` — konfiqurasiyanın CANLI mənbəyi."""
    if not UUID_RE.match(dataset_id or ""):
        raise RetrievalConfigUnavailable(f"dataset id UUID deyil: {dataset_id!r}")
    if not api_key:
        raise RetrievalConfigUnavailable(
            "dataset API açarı yoxdur (`AGENTPROOF_DATASET_KEY`) — canlı oxuma mümkün deyil"
        )
    return fetcher(f"{_api_root(base_url)}/v1/datasets/{dataset_id}", api_key)


# ------------------------------------------------------------------ probe
def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    return bool(value) if isinstance(value, bool) else None


def _text(value: Any) -> str:
    text = str(value or "").strip()
    return text or UNKNOWN


def resolve_dataset_id(
    app_id: str | None,
    dataset_id: str | None,
    container: str = DEFAULT_DB_CONTAINER,
    db: str = DEFAULT_DB_NAME,
    user: str = DEFAULT_DB_USER,
    runner: Runner = _docker_psql,
) -> tuple[str, str, list[str]]:
    """`(dataset_id, mənbə, xəbərdarlıqlar)`.

    App-dən oxunan id ilə verilən/env id fərqlənirsə, APP-inki götürülür və
    fərq xəbərdarlıq kimi qeyd olunur: qaçış app-ə sorğu atır, env-ə yox.
    """
    warnings: list[str] = []
    given = (dataset_id or "").strip()
    if not app_id:
        if not given:
            raise RetrievalConfigUnavailable(
                "nə app id (`--dify-app-id`), nə dataset id (`--dataset-id` / "
                "`AGENTPROOF_DATASET_ID`) verilib"
            )
        warnings.append(
            "dataset id app-dən YOX, kənardan götürüldü (`--dify-app-id` verilməyib) — "
            "app başqa dataset-ə bağlıdırsa konfiqurasiya səhv qeyd olunacaq"
        )
        return given, "given", warnings

    ids = read_app_dataset_ids(app_id, container=container, db=db, user=user, runner=runner)
    if len(ids) > 1:
        warnings.append(
            f"app-ə {len(ids)} dataset bağlıdır ({', '.join(ids)}) — yalnız birincisi "
            "qeyd olunur; `effective_top_k` bənd sayının TAMI deyil"
        )
    resolved = ids[0]
    if given and given != resolved:
        warnings.append(
            f"BAYAT DATASET İD: kənar dəyər {given} idi, app isə {resolved}-ə bağlıdır — "
            "app-inki götürüldü (qaçış app-ə sorğu atır)"
        )
    return resolved, "app-config", warnings


def probe_retrieval_config(
    app_id: str | None = None,
    dataset_id: str | None = None,
    base_url: str = "",
    api_key: str = "",
    container: str = DEFAULT_DB_CONTAINER,
    db: str = DEFAULT_DB_NAME,
    user: str = DEFAULT_DB_USER,
    runner: Runner = _docker_psql,
    fetcher: Fetcher = _http_fetch,
) -> RetrievalCheck:
    """Canlı retrieval konfiqurasiyası. Heç vaxt ATMIR — status qaytarır."""
    base_url = base_url or os.environ.get("DIFY_BASE_URL", "http://localhost:8088")
    api_key = api_key or os.environ.get("AGENTPROOF_DATASET_KEY", "")
    dataset_id = dataset_id if dataset_id is not None else os.environ.get(
        "AGENTPROOF_DATASET_ID", ""
    )

    warnings: list[str] = []
    source = ""
    try:
        resolved, source, warnings = resolve_dataset_id(
            app_id, dataset_id, container=container, db=db, user=user, runner=runner
        )
    except RetrievalConfigUnavailable as e:
        if (dataset_id or "").strip():
            resolved, source = dataset_id.strip(), "env"
            warnings = [
                f"app-dən dataset id oxunmadı ({e}) — `AGENTPROOF_DATASET_ID` götürüldü; "
                "env bayat ola bilər, bu dəyər TƏSDİQLƏNMƏMİŞDİR"
            ]
        else:
            return RetrievalCheck(
                status="unavailable",
                detail=f"dataset id müəyyən edilmədi: {e}",
                warnings=[
                    "retrieval konfiqurasiyası QEYD OLUNMADI — embedder və `top_k` "
                    "`unknown` qalır; bu qaçış konfiqurasiya baxımından öz-özünü "
                    "təsvir etmir"
                ],
            )

    try:
        payload = fetch_dataset(resolved, base_url, api_key, fetcher=fetcher)
    except RetrievalConfigUnavailable as e:
        return RetrievalCheck(
            status="unavailable",
            dataset_id=resolved,
            dataset_source=source,
            detail=f"`GET /v1/datasets/{resolved}` oxunmadı: {e}",
            warnings=warnings + [
                "retrieval konfiqurasiyası QEYD OLUNMADI — embedder və `top_k` "
                "`unknown` qalır; bu qaçış konfiqurasiya baxımından öz-özünü "
                "təsvir etmir"
            ],
        )

    retrieval = payload.get("retrieval_model_dict") or {}
    api_top_k = _int_or_none(retrieval.get("top_k"))
    embedding_model = _text(payload.get("embedding_model"))
    embedding_provider = _text(payload.get("embedding_model_provider"))
    search_method = _text(retrieval.get("search_method"))
    reranking = _bool_or_none(retrieval.get("reranking_enable"))

    if embedding_model == UNKNOWN:
        warnings.append(
            "dataset cavabında `embedding_model` yoxdur — embedder `unknown` qalır"
        )

    # --- `top_k` sabitlənibmi (yoxsa API default göstərir) -----------------
    status = "live"
    top_k_pinned: bool | None = None
    effective_top_k = api_top_k
    detail = f"`GET /v1/datasets/{resolved}` (canlı)"
    try:
        column = read_retrieval_model_column(
            resolved, container=container, db=db, user=user, runner=runner
        )
    except RetrievalConfigUnavailable as e:
        status = "partial"
        warnings.append(
            f"`datasets.retrieval_model` sütunu yoxlanmadı ({e}) — API-nin `top_k` "
            f"dəyəri ({api_top_k}) sütun NULL olsa da eyni görünür (OPS-05); "
            "rəqəm TƏSDİQLƏNMƏMİŞDİR"
        )
    else:
        top_k_pinned = column is not None
        if not top_k_pinned:
            status = "partial"
            effective_top_k = None
            warnings.append(
                f"`datasets.retrieval_model` NULL-dur — API `top_k: {api_top_k}` göstərir, "
                "amma agent yolu bu halda öz lokal defaultu ilə (2 bənd) işləyir "
                "(OPS-03). Faktiki dəyər naməlum sayılır; `IMPORT.md §1` ilə sabitlə."
            )
        else:
            column_top_k = _int_or_none(column.get("top_k"))
            if column_top_k is not None and column_top_k != api_top_k:
                status = "partial"
                effective_top_k = column_top_k
                warnings.append(
                    f"API `top_k: {api_top_k}`, sütun `top_k: {column_top_k}` — "
                    "sütun götürüldü (retrieval onu oxuyur)"
                )

    return RetrievalCheck(
        status=status,
        dataset_id=resolved,
        dataset_name=str(payload.get("name") or ""),
        dataset_source=source,
        embedding_model=embedding_model,
        embedding_provider=embedding_provider,
        effective_top_k=effective_top_k,
        reranking_enabled=reranking,
        search_method=search_method,
        top_k_pinned=top_k_pinned,
        api_top_k=api_top_k,
        detail=detail,
        warnings=warnings,
    )


def apply_retrieval(record: RunRecord, check: RetrievalCheck) -> RunRecord:
    """Canlı oxunuşu qaçış artefaktına yazır (`totals` ilə birlikdə)."""
    record.embedding_model = check.embedding_model
    record.embedding_provider = check.embedding_provider
    record.effective_top_k = check.effective_top_k
    record.reranking_enabled = check.reranking_enabled
    record.totals["retrieval_check"] = check.to_dict()
    return record

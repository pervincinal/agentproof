"""`usage.model` etiketini AVTORİTET mənbədən yoxlayır.

Problem (pilotdan): Dify-ın `message_end.metadata.usage` bloku model ADINI
ümumiyyətlə vermir. Ona görə etiket kənardan — `AGENTPROOF_SUT_MODEL` mühit
dəyişənindən — gəlirdi. Kimsə Dify app-ində modeli dəyişib env-i yeniləməsə,
`pricing/models.yaml` YANLIŞ dərəcə ilə hesablayır və xərc hesabatı səssizcə
başqa modelə yazılır. Səssiz yanlış rəqəm, yoxluqdan pisdir.

Avtoritet mənbə Dify-ın öz bazasıdır:

    apps.app_model_config_id -> app_model_configs.model ->> 'name'

⚠️ `app_model_configs`-da HƏMİN app üçün BİR NEÇƏ sətir olur (hər redaktə yeni
sətir yaradır). `where app_id = ...` bayat sətri qaytara bilər — canlı bazada
məhz belədir. Ona görə sorğu HƏMİŞƏ `apps.app_model_config_id` ilə join edir.

Davranış:
  * uyğunsuzluq        -> `SutModelMismatch` (qaçış AÇIQ XƏTA ilə dayanır)
  * etiket boşdur      -> bazadakı ad götürülür (`adopted`)
  * baza əlçatmazdır   -> XƏBƏRDARLIQ, qaçış davam edir, hesabata düşür
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

DEFAULT_DB_CONTAINER = os.environ.get("AGENTPROOF_DIFY_DB_CONTAINER", "docker-db_postgres-1")
DEFAULT_DB_NAME = os.environ.get("AGENTPROOF_DIFY_DB_NAME", "dify")
DEFAULT_DB_USER = os.environ.get("AGENTPROOF_DIFY_DB_USER", "postgres")

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

#: `app_model_config_id` ilə join — bayat konfiqurasiya sətrini oxumamaq üçün.
MODEL_QUERY = (
    "select amc.model::text from apps a "
    "join app_model_configs amc on amc.id = a.app_model_config_id "
    "where a.id = '{app_id}';"
)

Runner = Callable[[list[str]], str]


class SutModelUnavailable(RuntimeError):
    """Avtoritet mənbə oxunmadı — yoxlama edilə bilmir (ölümcül DEYİL)."""


class SutModelMismatch(RuntimeError):
    """Elan edilən model app-in real modeli deyil — qaçış dayanmalıdır."""


@dataclass(frozen=True)
class ModelCheck:
    status: str          # match | adopted | mismatch | unavailable | skipped
    declared: str
    actual: str
    detail: str = ""

    @property
    def model(self) -> str:
        """Hesabatda istifadə olunacaq ad — mümkünsə avtoritet olan."""
        return self.actual or self.declared

    def to_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "declared": self.declared,
            "actual": self.actual,
            "detail": self.detail,
        }


def _docker_psql(args: list[str]) -> str:
    if shutil.which("docker") is None:
        raise SutModelUnavailable("`docker` PATH-da yoxdur")
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        raise SutModelUnavailable(f"{type(e).__name__}: {e}") from e
    if proc.returncode != 0:
        raise SutModelUnavailable(
            f"psql exit {proc.returncode}: {(proc.stderr or '').strip()[:200]}"
        )
    return proc.stdout


def read_app_model(
    app_id: str,
    container: str = DEFAULT_DB_CONTAINER,
    db: str = DEFAULT_DB_NAME,
    user: str = DEFAULT_DB_USER,
    runner: Runner = _docker_psql,
) -> str:
    """App-in HAZIRDA aktiv model adı. Oxuna bilməsə `SutModelUnavailable`."""
    if not UUID_RE.match(app_id or ""):
        raise SutModelUnavailable(f"app id UUID deyil: {app_id!r}")
    out = runner(
        [
            "docker", "exec", container,
            "psql", "-U", user, "-d", db, "-tAc",
            MODEL_QUERY.format(app_id=app_id),
        ]
    )
    row = (out or "").strip()
    if not row:
        raise SutModelUnavailable(f"app tapılmadı və ya model konfiqurasiyası boşdur: {app_id}")
    try:
        payload = json.loads(row.splitlines()[0])
    except ValueError as e:
        raise SutModelUnavailable(f"model JSON parse olunmadı: {e}") from e
    name = str((payload or {}).get("name") or "").strip()
    if not name:
        raise SutModelUnavailable(f"model JSON-unda `name` yoxdur: {row[:200]}")
    return name


def verify_sut_model(
    declared: str,
    app_id: str | None,
    container: str = DEFAULT_DB_CONTAINER,
    db: str = DEFAULT_DB_NAME,
    user: str = DEFAULT_DB_USER,
    runner: Runner = _docker_psql,
) -> ModelCheck:
    """Elan edilən etiketi app-in real modeli ilə tutuşdurur.

    Uyğunsuzluqda `SutModelMismatch` ATIR — susqun davam etmək, xərci başqa
    modelə yazmaq deməkdir.
    """
    declared = (declared or "").strip()
    if not app_id:
        return ModelCheck(
            status="skipped",
            declared=declared,
            actual="",
            detail=(
                "app id verilməyib (`--dify-app-id` / AGENTPROOF_DIFY_APP_ID) — "
                "`usage.model` yoxlanılmamış ƏL ETİKETİDİR"
            ),
        )
    try:
        actual = read_app_model(app_id, container=container, db=db, user=user, runner=runner)
    except SutModelUnavailable as e:
        return ModelCheck(
            status="unavailable",
            declared=declared,
            actual="",
            detail=(
                f"Dify bazası oxunmadı ({e}) — `usage.model` yoxlanılmamış ƏL ETİKETİDİR; "
                "app-də model dəyişibsə xərc yanlış dərəcə ilə hesablanacaq"
            ),
        )
    if not declared:
        return ModelCheck(
            status="adopted",
            declared="",
            actual=actual,
            detail=f"etiket verilməyib; app-in real modeli götürüldü: {actual}",
        )
    if declared != actual:
        raise SutModelMismatch(
            f"MODEL UYĞUNSUZLUĞU — qaçış dayandırıldı.\n"
            f"  elan edilən (AGENTPROOF_SUT_MODEL / --model): {declared!r}\n"
            f"  app-in real modeli (apps.app_model_config_id -> app_model_configs.model): {actual!r}\n"
            f"  app id: {app_id}\n"
            f"  Xərc hesabatı {declared!r} dərəcəsi ilə çıxardı — bu, YANLIŞ rəqəmdir.\n"
            f"  Düzəliş: ya app-də modeli geri qaytar, ya AGENTPROOF_SUT_MODEL={actual} et\n"
            f"  və `agentproof/pricing/models.yaml`-da həmin model üçün dərəcə olduğunu yoxla."
        )
    return ModelCheck(status="match", declared=declared, actual=actual)

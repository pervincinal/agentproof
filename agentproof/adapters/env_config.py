"""Adapter konfiqurasiyası MÜHİT DƏYİŞƏNLƏRİNDƏN — açar CLI-a düşmür.

Bu funksiya `evals/run.py`-də yaşayırdı, amma `run.py` modul səviyyəsində
`inspect_ai` idxal edir. `preflight` isə auditdən ƏVVƏL qaçır (çox vaxt
`inspect_ai` quraşdırılmamış mühitdə) və eyni konfiqurasiyaya ehtiyacı var.
İki nüsxə saxlansaydı, biri digərindən sürüşərdi: qaçış bir base_url-a,
preflight başqasına baxar və hesabat SƏHV hədəfi təsvir edərdi.

Açar dəyərləri BURADA loga yazılmır və qaytarılan lüğət yalnız adapterə gedir.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

#: `json_http` sahə xəritəsi: JSON fayl yolu VƏ YA birbaşa JSON sətri.
JSON_MAP_ENV = "AGENTPROOF_JSON_MAP"


def adapter_config_from_env(target: str) -> dict[str, Any]:
    """`--target <adapter>` üçün mühitdən oxunan konfiqurasiya."""
    if target == "dify_http":
        return _env_keys({
            "DIFY_BASE_URL": "base_url",
            "DIFY_API_KEY": "api_key",
            "DIFY_APP_VERSION": "version",
        })
    if target == "json_http":
        config = _env_keys({
            "AGENTPROOF_JSON_URL": "url",
            "AGENTPROOF_JSON_API_KEY": "api_key",
            "AGENTPROOF_JSON_HEALTH_URL": "health_url",
            "AGENTPROOF_JSON_QUERY_FIELD": "query_field",
            "AGENTPROOF_JSON_VERSION": "version",
        })
        config.update(load_json_map(os.environ.get(JSON_MAP_ENV, "")))
        return config
    return {}


def load_json_map(spec: str) -> dict[str, Any]:
    """Sahə xəritəsi: fayl yolu və ya inline JSON.

    Boş sətir BOŞ lüğət qaytarır — yəni `FieldMap` default namizədləri
    işləyir. Bu, susqun DEYİL: hansı yolun tutduğu hər cavabda
    `raw["mapped_paths"]`-da görünür.
    """
    spec = (spec or "").strip()
    if not spec:
        return {}
    text = spec if spec.startswith("{") else Path(spec).read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{JSON_MAP_ENV}: JSON obyekt gözlənilir, {type(data).__name__} gəldi")
    return data


def _env_keys(mapping: dict[str, str]) -> dict[str, Any]:
    return {arg: os.environ[env] for env, arg in mapping.items() if os.environ.get(env)}

"""Qaçış artefaktı öz retrieval konfiqurasiyasını daşıyır (LIM-E06 / AP-019).

Niyə test lazımdır: embedder adı və `top_k` `RunRecord`-da SAXLANMIRDI, yəni
hesabatın iki ən yük daşıyan parametri kənar sənəddən oxunurdu. VALID-03-də
sənəd `top_k: 4` yazırdı, faktiki dəyər **8** idi — fərqi yalnız canlı sistemə
sorğu ataraq tapmaq mümkün oldu.

Bu faylda hər yolun davranışı bağlanır:
  * dəyərlər CANLI sistemdən yazılır (dataset API + app-ın bağlı dataset-i);
  * bayat dataset id (env) app-ın həqiqi dataset-ini üstələyə BİLMİR;
  * oxuna bilməyəndə açıq `unknown` / `None` — səssiz default YOX;
  * `retrieval_model` sütunu NULL olanda API-nin rəqəmi qeyd EDİLMİR;
  * köhnə (schema_version 1) artefakt oxunanda sınmır.
"""

from __future__ import annotations

import json

import pytest

from agentproof.report.pr_comment import retrieval_block, retrieval_line
from agentproof.runner.retrieval_config import (
    DATASET_CONFIGS_QUERY,
    RETRIEVAL_MODEL_QUERY,
    RetrievalCheck,
    RetrievalConfigUnavailable,
    apply_retrieval,
    fetch_dataset,
    probe_retrieval_config,
    read_app_dataset_ids,
)
from agentproof.types import SCHEMA_VERSION, UNKNOWN, RunRecord

#: Mühit dəyişənləri testə SIZMAMALIDIR: `probe_retrieval_config()` bilərəkdən
#: env-ə düşür, yəni `.env`-i yükləyən qabıqda test yalançı yaşıl olardı.
ENV_KEYS = ("AGENTPROOF_DATASET_ID", "AGENTPROOF_DATASET_KEY", "DIFY_BASE_URL")


@pytest.fixture(autouse=True)
def _no_env_leak(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


APP_ID = "4daef326-beb5-4c36-88a4-167d20194729"
DATASET_V2 = "1623dd7e-3e9e-4a8c-97c3-d66fdbac8e39"
DATASET_V1 = "e1471e22-18f8-4b30-aeb1-012c048e38a5"


# ------------------------------------------------------------------ saxta canlı sistem
def _dataset_payload(
    dataset_id: str = DATASET_V2,
    embedder: str = "bge-m3",
    provider: str = "langgenius/ollama/ollama",
    top_k: int = 8,
) -> dict:
    """`GET /v1/datasets/{id}` cavabının canlı sistemdən götürülmüş forması."""
    return {
        "id": dataset_id,
        "name": "Aurora Goods Policies v2",
        "indexing_technique": "high_quality",
        "embedding_model": embedder,
        "embedding_model_provider": provider,
        # ⚠️ Canlı cavabda `retrieval_model` sahəsi YOXDUR (OPS-05) — yalnız bu.
        "retrieval_model_dict": {
            "search_method": "semantic_search",
            "reranking_enable": False,
            "top_k": top_k,
            "score_threshold_enabled": False,
            "score_threshold": None,
        },
    }


def _fetcher(payload: dict, capture: list[str] | None = None):
    def fetch(url: str, api_key: str) -> dict:
        if capture is not None:
            capture.append(url)
        return payload

    return fetch


def _failing_fetcher(message: str):
    def fetch(url: str, api_key: str) -> dict:
        raise RetrievalConfigUnavailable(message)

    return fetch


def _psql_runner(
    dataset_ids: list[str] | None = (DATASET_V2,),
    retrieval_model: dict | None = None,
    capture: list[list[str]] | None = None,
):
    """Saxta `docker exec psql` — sorğuya görə cavab verir."""
    if retrieval_model is None:
        retrieval_model = {"top_k": 8, "search_method": "semantic_search"}

    def run(args: list[str]) -> str:
        if capture is not None:
            capture.append(args)
        query = args[-1]
        if "dataset_configs" in query:
            if dataset_ids is None:
                return "\n"
            return json.dumps(
                {
                    "top_k": 4,  # app-ın ÖZ dəyəri — retrieval onu oxumur (OPS-03)
                    "datasets": {
                        "datasets": [
                            {"dataset": {"enabled": True, "id": i}} for i in dataset_ids
                        ]
                    },
                }
            ) + "\n"
        if "retrieval_model" in query:
            return ("" if retrieval_model is False else json.dumps(retrieval_model)) + "\n"
        raise AssertionError(f"gözlənilməyən sorğu: {query}")

    return run


# ------------------------------------------------------- 1. sahələr YAZILIR
def test_run_record_carries_live_retrieval_config():
    """DoD #1 — sahələr artefakta düşür və JSON-a yazılır."""
    check = probe_retrieval_config(
        app_id=APP_ID,
        base_url="http://localhost:8088",
        api_key="dataset-test",
        runner=_psql_runner(),
        fetcher=_fetcher(_dataset_payload()),
    )
    assert check.status == "live"

    record = RunRecord(
        run_id="r1", target="dify_http", target_version="1.17.0",
        model="claude-sonnet-5", dataset_hash="abc", started_at="2026-08-28T00:00:00",
    )
    apply_retrieval(record, check)

    assert record.embedding_model == "bge-m3"
    assert record.embedding_provider == "langgenius/ollama/ollama"
    assert record.effective_top_k == 8
    assert record.reranking_enabled is False

    payload = json.loads(json.dumps(record.to_dict(), ensure_ascii=False))
    assert payload["embedding_model"] == "bge-m3"
    assert payload["effective_top_k"] == 8
    # Sxem versiyası artefaktın öz içindədir; AP-024/AP-026 ilə 3-ə, AP-042 ilə
    # 4-ə qalxdı (dataset-in İKİ imzası: seçim + tam fayl). Köhnə 1/2/3
    # oxunmağa davam edir — aşağıdakı
    # `test_old_schema_version_1_record_still_loads` bunu kilidləyir.
    assert payload["schema_version"] == SCHEMA_VERSION == 4
    # Səbəb izi də artefaktdadır — rəqəmin haradan gəldiyi SÜBUT olunmalıdır.
    assert payload["totals"]["retrieval_check"]["dataset_source"] == "app-config"

    again = RunRecord.from_dict(payload)
    assert again.effective_top_k == 8
    assert again.embedding_model == "bge-m3"
    assert again.reranking_enabled is False


def test_values_come_from_the_dataset_api_not_from_a_config_file():
    """Tapşırığın mahiyyəti: mənbə `GET /v1/datasets/{id}`-dir."""
    urls: list[str] = []
    probe_retrieval_config(
        app_id=APP_ID,
        base_url="http://localhost:8088/v1",  # `/v1` ilə də, onsuz da işləməlidir
        api_key="dataset-test",
        runner=_psql_runner(),
        fetcher=_fetcher(_dataset_payload(), capture=urls),
    )
    assert urls == [f"http://localhost:8088/v1/datasets/{DATASET_V2}"]


# ------------------------------------------- 2. dataset id AVTORİTET mənbədən
def test_app_bound_dataset_wins_over_stale_env_id():
    """Canlı sistemdə env köhnə dataset-i göstərirdi, app başqasına bağlı idi.

    Env-ə güvənsək, hesabat yenidən YANLIŞ konfiqurasiyanı qeyd edərdi —
    yəni LIM-E06 düzəlmiş kimi görünüb əslində düzəlməzdi.
    """
    check = probe_retrieval_config(
        app_id=APP_ID,
        dataset_id=DATASET_V1,           # bayat env dəyəri
        api_key="dataset-test",
        runner=_psql_runner(dataset_ids=[DATASET_V2]),
        fetcher=_fetcher(_dataset_payload()),
    )
    assert check.dataset_id == DATASET_V2
    assert check.dataset_source == "app-config"
    assert any("BAYAT DATASET İD" in w for w in check.warnings)


def test_dataset_configs_query_joins_on_the_active_config():
    """`app_model_configs`-da app üzrə bir neçə sətir olur — join məcburidir."""
    assert "a.app_model_config_id" in DATASET_CONFIGS_QUERY
    assert "join app_model_configs" in DATASET_CONFIGS_QUERY
    assert "retrieval_model" in RETRIEVAL_MODEL_QUERY


def test_ids_must_be_uuids():
    """Dəyər sorğuya sətir kimi yapışdırılır."""
    with pytest.raises(RetrievalConfigUnavailable, match="UUID deyil"):
        read_app_dataset_ids("'; drop table apps; --", runner=_psql_runner())
    with pytest.raises(RetrievalConfigUnavailable, match="UUID deyil"):
        fetch_dataset("not-a-uuid", "http://x", "k", fetcher=_fetcher({}))


def test_multiple_bound_datasets_are_flagged_not_hidden():
    check = probe_retrieval_config(
        app_id=APP_ID,
        api_key="dataset-test",
        runner=_psql_runner(dataset_ids=[DATASET_V2, DATASET_V1]),
        fetcher=_fetcher(_dataset_payload()),
    )
    assert any("2 dataset bağlıdır" in w for w in check.warnings)


# --------------------------------------- 3. oxunmayanda AÇIQ `unknown` qalır
def test_unreadable_api_yields_explicit_unknown_not_a_default():
    """DoD #3 — səssiz default YOXDUR."""
    check = probe_retrieval_config(
        app_id=APP_ID,
        api_key="dataset-test",
        runner=_psql_runner(),
        fetcher=_failing_fetcher("HTTP 401"),
    )
    assert check.status == "unavailable"
    assert check.embedding_model == UNKNOWN
    assert check.embedding_provider == UNKNOWN
    assert check.effective_top_k is None
    assert check.warnings, "oxunmadıqda hesabatda görünən xəbərdarlıq olmalıdır"

    record = RunRecord(
        run_id="r2", target="dify_http", target_version="", model="", dataset_hash="",
        started_at="",
    )
    apply_retrieval(record, check)
    assert record.embedding_model == UNKNOWN
    assert record.effective_top_k is None
    assert "⚠️" in retrieval_line(record)
    assert retrieval_block(record), "xəbərdarlıq PR şərhində görünməlidir"


def test_missing_api_key_is_reported_not_guessed():
    check = probe_retrieval_config(
        app_id=APP_ID,
        api_key="",
        runner=_psql_runner(),
        fetcher=_fetcher(_dataset_payload()),
    )
    assert check.status == "unavailable"
    assert check.embedding_model == UNKNOWN
    assert "AGENTPROOF_DATASET_KEY" in check.detail


def test_no_app_id_and_no_dataset_id_is_unavailable():
    check = probe_retrieval_config(
        app_id=None, dataset_id="", api_key="k", fetcher=_fetcher(_dataset_payload())
    )
    assert check.status == "unavailable"
    assert check.effective_top_k is None


def test_missing_embedding_model_in_payload_stays_unknown():
    payload = _dataset_payload()
    payload.pop("embedding_model")
    check = probe_retrieval_config(
        app_id=APP_ID,
        api_key="dataset-test",
        runner=_psql_runner(),
        fetcher=_fetcher(payload),
    )
    assert check.embedding_model == UNKNOWN
    assert any("embedding_model" in w for w in check.warnings)


# ------------------------- 4. API-nin `top_k`-sı NULL sütunda YANILDICIDIR
def test_null_retrieval_model_column_is_not_recorded_as_the_api_number():
    """OPS-03/OPS-05 tələsi.

    Sütun NULL olanda API yenə `top_k: 4` qaytarır, amma agent yolu 2 bənd
    çəkir. `4` yazmaq — səssizcə YANLIŞ rəqəm qeyd etmək deməkdir.
    """
    check = probe_retrieval_config(
        app_id=APP_ID,
        api_key="dataset-test",
        runner=_psql_runner(dataset_ids=[DATASET_V1], retrieval_model=False),
        fetcher=_fetcher(_dataset_payload(dataset_id=DATASET_V1, top_k=4)),
    )
    assert check.status == "partial"
    assert check.top_k_pinned is False
    assert check.api_top_k == 4
    assert check.effective_top_k is None, "sabitlənməmiş `top_k` rəqəm kimi yazılmamalıdır"
    assert any("NULL" in w for w in check.warnings)


def test_unreadable_db_keeps_the_number_but_marks_it_unverified():
    def runner(args: list[str]) -> str:
        if "dataset_configs" in args[-1]:
            return _psql_runner()(args)
        raise RetrievalConfigUnavailable("`docker` PATH-da yoxdur")

    check = probe_retrieval_config(
        app_id=APP_ID,
        api_key="dataset-test",
        runner=runner,
        fetcher=_fetcher(_dataset_payload()),
    )
    assert check.status == "partial"
    assert check.effective_top_k == 8
    assert check.top_k_pinned is None
    assert any("TƏSDİQLƏNMƏMİŞ" in w for w in check.warnings)


# ------------------------------------------ 5. KÖHNƏ artefakt sınmır
def test_old_schema_version_1_record_still_loads():
    """DoD #4 — sahələr yoxdursa `unknown` / `None`, istisna YOX."""
    legacy = {
        "schema_version": 1,
        "run_id": "old-run",
        "target": "dify_http",
        "target_version": "1.17.0",
        "model": "claude-sonnet-5",
        "dataset_hash": "deadbeef",
        "started_at": "2026-08-27T10:00:00",
        "results": [],
        "totals": {"n_cases": 0, "pass_rate": 0.0},
    }
    record = RunRecord.from_dict(legacy)

    assert record.schema_version == 1
    assert record.embedding_model == UNKNOWN
    assert record.embedding_provider == UNKNOWN
    assert record.effective_top_k is None
    assert record.reranking_enabled is None
    # Köhnə artefakt hesabatda "ölçüldü" kimi görünməməlidir.
    assert "QEYD OLUNMAYIB" in retrieval_line(record)


def test_real_legacy_report_artifacts_still_load():
    """Diskdəki HƏQİQİ köhnə qaçışlar oxunmalıdır — sintetik JSON bəs etmir."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "reports"
    paths = sorted(root.glob("*/*.json"))[:12]
    loaded = 0
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(raw, dict) or "run_id" not in raw or "results" not in raw:
            continue
        record = RunRecord.from_dict(raw)
        assert isinstance(record.embedding_model, str)
        assert record.effective_top_k is None or isinstance(record.effective_top_k, int)
        loaded += 1
    assert loaded, "köhnə RunRecord tapılmadı — test mənasız yaşıl olardı"


def test_partial_and_skipped_states_are_visible_in_the_report():
    record = RunRecord(
        run_id="r3", target="dify_http", target_version="", model="", dataset_hash="",
        started_at="",
    )
    apply_retrieval(
        record,
        RetrievalCheck(
            status="skipped",
            detail="--skip-retrieval-check ilə bilərəkdən keçilib",
            warnings=["retrieval konfiqurasiyası bilərəkdən oxunmadı"],
        ),
    )
    line = retrieval_line(record)
    assert "YOXLANILMADI" in line
    assert UNKNOWN in line
    assert retrieval_block(record)

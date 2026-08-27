"""`usage.model` etiketi AVTORİTET mənbədən yoxlanır (runner/sut_model.py).

Niyə test lazımdır: pilotda model adı `AGENTPROOF_SUT_MODEL` env dəyişənindən
gəlirdi. Kimsə Dify app-ində modeli dəyişib env-i unutsa, xərc SƏSSİZCƏ yanlış
modelə yazılırdı — hesabat isə yaşıl və inandırıcı görünürdü. Bu faylda hər
yolun davranışı bağlanır: uyğunluq, uyğunsuzluq (DAYAN), boş etiket (götür),
baza əlçatmaz (XƏBƏRDARLIQ).
"""

from __future__ import annotations

import json

import pytest

from agentproof.runner.sut_model import (
    MODEL_QUERY,
    SutModelMismatch,
    SutModelUnavailable,
    read_app_model,
    verify_sut_model,
)

APP_ID = "4daef326-beb5-4c36-88a4-167d20194729"


def _runner(model_name: str, capture: list[list[str]] | None = None):
    def run(args: list[str]) -> str:
        if capture is not None:
            capture.append(args)
        return json.dumps(
            {"provider": "langgenius/anthropic/anthropic", "name": model_name, "mode": "chat"}
        ) + "\n"

    return run


def _failing_runner(message: str):
    def run(args: list[str]) -> str:
        raise SutModelUnavailable(message)

    return run


# ---------------------------------------------------------------- sorğunun özü
def test_query_joins_on_the_active_config_not_on_app_id():
    """`app_model_configs`-da app üzrə BİR NEÇƏ sətir olur (canlı bazada da belədir).

    `where app_id = ...` bayat sətri qaytara bilər; ona görə sorğu
    `apps.app_model_config_id` ilə join etməlidir. Bu, sadəcə üslub deyil —
    yanlış sətir yanlış model adı deməkdir.
    """
    assert "a.app_model_config_id" in MODEL_QUERY
    assert "join app_model_configs" in MODEL_QUERY


def test_app_id_must_be_a_uuid():
    """Sorğuya sətir kimi yapışdırılır — UUID olmayan dəyər qəbul edilmir."""
    with pytest.raises(SutModelUnavailable, match="UUID deyil"):
        read_app_model("'; drop table apps; --", runner=_runner("claude-sonnet-5"))


def test_read_app_model_returns_the_configured_name():
    captured: list[list[str]] = []
    name = read_app_model(APP_ID, runner=_runner("claude-sonnet-5", captured))
    assert name == "claude-sonnet-5"
    assert APP_ID in " ".join(captured[0])


# ------------------------------------------------------------------ yoxlama
def test_match_is_reported_and_run_continues():
    check = verify_sut_model("claude-sonnet-5", APP_ID, runner=_runner("claude-sonnet-5"))
    assert check.status == "match"
    assert check.model == "claude-sonnet-5"


def test_mismatch_stops_the_run_with_both_names_in_the_message():
    """Susqun davam etmək yasaqdır: xəta HƏR İKİ adı və app id-ni göstərməlidir."""
    with pytest.raises(SutModelMismatch) as exc:
        verify_sut_model("claude-sonnet-5", APP_ID, runner=_runner("claude-opus-5"))
    message = str(exc.value)
    assert "claude-sonnet-5" in message and "claude-opus-5" in message
    assert APP_ID in message
    assert "AGENTPROOF_SUT_MODEL" in message


def test_empty_label_adopts_the_authoritative_name():
    check = verify_sut_model("", APP_ID, runner=_runner("claude-haiku-4-5"))
    assert check.status == "adopted"
    assert check.model == "claude-haiku-4-5"


def test_unavailable_database_warns_but_does_not_stop():
    """Bazasız mühitdə (CI) qaçış davam edir — amma səbəb hesabata düşür."""
    check = verify_sut_model(
        "claude-sonnet-5", APP_ID, runner=_failing_runner("docker yoxdur")
    )
    assert check.status == "unavailable"
    assert "docker yoxdur" in check.detail
    assert check.model == "claude-sonnet-5"  # etiket qalır, amma yoxlanılmamış


def test_missing_app_id_is_reported_as_unverified():
    check = verify_sut_model("claude-sonnet-5", None)
    assert check.status == "skipped"
    assert "ƏL ETİKETİDİR" in check.detail


def test_check_serialises_into_the_run_record():
    check = verify_sut_model("claude-sonnet-5", APP_ID, runner=_runner("claude-sonnet-5"))
    assert check.to_dict() == {
        "status": "match",
        "declared": "claude-sonnet-5",
        "actual": "claude-sonnet-5",
        "detail": "",
    }


def test_empty_result_means_the_app_does_not_exist():
    with pytest.raises(SutModelUnavailable, match="app tapılmadı"):
        read_app_model(APP_ID, runner=lambda args: "\n")


def test_unparseable_row_is_not_silently_treated_as_a_model_name():
    with pytest.raises(SutModelUnavailable, match="parse olunmadı"):
        read_app_model(APP_ID, runner=lambda args: "not json\n")


# ------------------------------------------------------------------- canlı
def test_live_dify_app_model_is_priceable():
    """Canlı mühitdə: app-in real modeli qiymət cədvəlində OLMALIDIR.

    Bazasız mühitdə (CI) atlanır. Bazalı mühitdə isə tutduğu şey real bir
    nasazlıqdır: app-də cədvəldə olmayan modelə keçilsə, `cost_under` bütün
    case-lərdə `skipped` verər və xərc hesabatı boş çıxar.
    """
    from agentproof.pricing.table import load_prices

    try:
        actual = read_app_model(APP_ID)
    except SutModelUnavailable as e:
        pytest.skip(f"Dify bazası əlçatmazdır: {e}")
    assert actual in load_prices().models, (
        f"app-in modeli {actual!r} `pricing/models.yaml`-da yoxdur — "
        "xərc hesablana bilməz"
    )


def test_lanes_example_file_is_valid_and_uses_distinct_namespaces():
    """`evals/lanes.example.json` şablonu qaçırıla bilən olmalıdır.

    Nümunə fayl sınıq olsa, ilk paralel qaçışı quran adam səhv formatı
    kopyalayacaq.
    """
    import json as _json
    from pathlib import Path

    from agentproof.runner.isolation import build_lane_pool

    spec = _json.loads(
        (Path(__file__).resolve().parents[2] / "evals" / "lanes.example.json").read_text()
    )
    pool = build_lane_pool(spec)
    assert pool.isolated and pool.size == len(spec)
    assert len({lane.session for lane in pool.lanes}) == pool.size

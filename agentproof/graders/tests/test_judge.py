"""requires_justification (LLM-as-judge) — REAL API ÇAĞIRIŞI YOXDUR.

Bütün testlər mock klient üzərində qaçır: judge-in özü test edilməlidir,
amma test dəsti açar tələb etməməlidir (grader-eng.md + tapşırıq şərti).
"""

from __future__ import annotations

import json

import pytest

from agentproof.graders import registry
from agentproof.graders.judge import (
    DEFAULT_JUDGE_MODEL,
    VERDICTS,
    AnthropicJudgeClient,
    JudgeCache,
    JudgeConfig,
    JudgeDecision,
    JudgeProtocolError,
    JudgeRaw,
    RubricJudge,
    get_rubric,
    model_tier,
    supports_temperature,
)
from agentproof.types import Case


# ------------------------------------------------------------------ köməkçilər
class FakeJudgeClient:
    """Verilən JSON-u qaytaran mock. Şəbəkəyə çıxmır."""

    def __init__(self, payload: dict | str, model: str = "claude-opus-5") -> None:
        self.payload = payload
        self.model = model
        self.calls: list[tuple[str, str, dict]] = []

    def complete(self, system: str, user: str, schema: dict) -> JudgeRaw:
        self.calls.append((system, user, schema))
        text = self.payload if isinstance(self.payload, str) else json.dumps(
            self.payload, ensure_ascii=False
        )
        return JudgeRaw(text=text, meta={"model": self.model, "temperature_applied": False})


PLUS_CASE = Case(
    id="ORD-10011",
    input="Aurora Plus üzvüyəm, 10 gün əvvəl çatdırılıb. Qaytarma müddətim nə qədərdir?",
    grader="requires_justification",
    tags=["grading:requires_justification"],
    expect={
        "answer_value": "30 gün",
        "controlling_rule": "return_window_plus_member = 30 gün (AKTİV), rank 5",
        "decoy_rules": ["return_window_standard = 30 gün — BAYAT (T-01)"],
    },
)


def _judge(payload) -> tuple[RubricJudge, FakeJudgeClient]:
    client = FakeJudgeClient(payload)
    return RubricJudge().bind(client), client


def _response(text: str):
    from agentproof.types import AgentResponse

    return AgentResponse(text=text)


# ------------------------------------------------------------------- registry
def test_judge_is_registered_with_judge_kind():
    assert "requires_justification" in registry.names()
    assert registry.kind("requires_justification") == "judge"


def test_judge_lands_in_judge_stage_not_cheap():
    """Bahalı grader hər PR-da qaçmamalıdır (STACK.md §8.6, 6 dəqiqə qaydası)."""
    from agentproof.runner.stages import STAGE_JUDGE, case_stage, filter_stage

    assert case_stage(PLUS_CASE) == STAGE_JUDGE
    assert filter_stage([PLUS_CASE], "cheap") == []
    assert filter_stage([PLUS_CASE], "judge") == [PLUS_CASE]


# ------------------------------------------------- bilərəkdən KEÇƏN / SINAN hal
def test_justified_answer_passes():
    judge, _ = _judge({"verdict": "justified", "reason": "üzvlük göstərilir", "confidence": 0.93})
    result = judge.grade(
        PLUS_CASE,
        _response("Aurora Plus üzvü olduğunuz üçün 30 gün — standart pəncərə 14 gündür."),
    )
    assert result.passed
    assert result.score == 1.0
    assert result.evidence["verdict"] == "justified"
    assert result.evidence["confidence"] == 0.93
    assert result.evidence["rubric_version"] == get_rubric("requires_justification").version


def test_right_number_wrong_path_fails():
    """Dəstin bütün mövcudluq səbəbi: rəqəm düz, yol bayat (TRAPS.md §5)."""
    judge, _ = _judge({"verdict": "wrong", "reason": "bayat standart pəncərə", "confidence": 0.88})
    result = judge.grade(PLUS_CASE, _response("Standart qaytarma pəncərəmiz 30 gündür."))
    assert not result.passed
    assert "bayat" in result.reason


def test_right_number_without_justification_fails():
    judge, _ = _judge({"verdict": "unjustified", "reason": "səbəb yoxdur", "confidence": 0.8})
    result = judge.grade(PLUS_CASE, _response("Qaytarma müddətiniz 30 gündür."))
    assert not result.passed
    assert not result.skipped
    assert "idarəedici şərt göstərilmir" in result.reason


# -------------------------------------------------------------- struktur çıxış
def test_prompt_contains_controlling_rule_and_decoys():
    judge, client = _judge({"verdict": "justified", "reason": "ok", "confidence": 1.0})
    judge.grade(PLUS_CASE, _response("30 gün, çünki Plus üzvüsünüz."))
    _system, user, schema = client.calls[0]
    assert "return_window_plus_member" in user
    assert "BAYAT" in user
    assert "30 gün, çünki Plus üzvüsünüz." in user
    assert schema["properties"]["verdict"]["enum"] == list(VERDICTS)
    assert schema["required"] == ["verdict", "reason", "confidence"]
    assert schema["additionalProperties"] is False


def test_rubric_forbids_style_criteria_explicitly():
    """Rubrika üslub yanlılığını AÇIQ qadağan etməlidir — mətn reqressiya testi."""
    system = get_rubric("requires_justification").system
    for phrase in ["uzunluğu", "tonu", "əminliyi", "formatı"]:
        assert phrase in system
    assert "TƏSİR ETMİR" in system


@pytest.mark.parametrize(
    "payload",
    [
        "bu JSON deyil",
        json.dumps({"verdict": "justified", "reason": "yalnız iki sahə"}),
        json.dumps({"verdict": "great", "reason": "r", "confidence": 1.0}),
        json.dumps({"verdict": "justified", "reason": "r", "confidence": "çox"}),
        json.dumps(["justified"]),
    ],
)
def test_malformed_judge_output_skips_not_passes(payload):
    """Yararsız judge cavabı `skipped`-dir — heç vaxt səssiz `passed` deyil."""
    judge, _ = _judge(payload)
    result = judge.grade(PLUS_CASE, _response("30 gün"))
    assert result.skipped
    assert not result.passed
    assert result.reason


def test_confidence_is_clamped():
    assert JudgeDecision.parse(
        json.dumps({"verdict": "wrong", "reason": "r", "confidence": 7})
    ).confidence == 1.0


def test_low_confidence_is_skipped_when_threshold_set():
    client = FakeJudgeClient({"verdict": "justified", "reason": "r", "confidence": 0.2})
    judge = RubricJudge(config=JudgeConfig(min_confidence=0.5)).bind(client)
    result = judge.grade(PLUS_CASE, _response("30 gün, Plus üzvüsünüz"))
    assert result.skipped
    assert "inamı" in result.reason


# ----------------------------------------------------------------- müqavilələr
def test_missing_expect_field_is_dataset_error_not_silent_pass():
    bad = Case(id="x", input="s", grader="requires_justification", expect={"answer_value": "30"})
    judge, _ = _judge({"verdict": "justified", "reason": "r", "confidence": 1.0})
    with pytest.raises(ValueError, match="controlling_rule"):
        judge.grade(bad, _response("30 gün"))


def test_unbound_judge_raises_instead_of_faking_a_verdict():
    with pytest.raises(RuntimeError, match="bind"):
        RubricJudge().grade(PLUS_CASE, _response("30 gün"))


def test_nonzero_temperature_is_rejected():
    with pytest.raises(ValueError, match="temperature"):
        JudgeConfig(temperature=0.7).validate()


def test_judge_must_be_stronger_than_sut():
    with pytest.raises(ValueError, match="güclü deyil"):
        JudgeConfig(model="claude-sonnet-4-6", sut_model="claude-opus-5").validate()
    JudgeConfig(model="claude-opus-5", sut_model="claude-sonnet-4-6").validate()


def test_default_judge_model_is_the_strongest_default():
    assert DEFAULT_JUDGE_MODEL == "claude-opus-5"
    assert model_tier("claude-opus-5") > model_tier("claude-sonnet-5")


def test_models_that_reject_sampling_do_not_receive_temperature():
    """Opus 5 `temperature` sahəsini 400 ilə rədd edir — göndərmirik, gizlətmirik."""
    assert not supports_temperature("claude-opus-5")
    assert supports_temperature("claude-sonnet-4-6")

    sent: dict = {}

    class _SDK:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kwargs):
                sent.update(kwargs)
                return type(
                    "R",
                    (),
                    {
                        "content": [type("B", (), {"type": "text", "text": '{"verdict":"wrong",'
                                                                          '"reason":"r","confidence":0.5}'})()],
                        "usage": type("U", (), {"input_tokens": 10, "output_tokens": 5})(),
                    },
                )()

    raw = AnthropicJudgeClient(model="claude-opus-5", client=_SDK()).complete("s", "u", {})
    assert "temperature" not in sent
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert raw.meta["temperature_applied"] is False

    sent.clear()
    raw = AnthropicJudgeClient(model="claude-sonnet-4-6", client=_SDK()).complete("s", "u", {})
    assert sent["temperature"] == 0.0
    assert raw.meta["temperature_applied"] is True


# ---------------------------------------------------------------- determinizm
def test_cache_makes_repeat_runs_identical_without_second_call(tmp_path):
    """API-də seed yoxdur — determinizmi keş verir. İkinci qaçış çağırış etmir."""
    client = FakeJudgeClient({"verdict": "justified", "reason": "r", "confidence": 0.9})
    config = JudgeConfig(cache_dir=str(tmp_path))
    first = RubricJudge(config=config).bind(client).grade(PLUS_CASE, _response("30 gün, Plus"))
    assert len(client.calls) == 1

    second = RubricJudge(config=config).bind(client).grade(PLUS_CASE, _response("30 gün, Plus"))
    assert len(client.calls) == 1, "keş işləmədi — ikinci çağırış getdi"
    assert second.evidence["verdict"] == first.evidence["verdict"]
    assert second.evidence["prompt_sha256"] == first.evidence["prompt_sha256"]
    assert second.evidence["cache_hit"] is True


def test_fingerprint_changes_with_answer_and_model():
    a = JudgeCache.fingerprint("m", "s", "cavab A")
    b = JudgeCache.fingerprint("m", "s", "cavab B")
    c = JudgeCache.fingerprint("m2", "s", "cavab A")
    assert len({a, b, c}) == 3


def test_graders_import_does_not_pull_in_the_anthropic_sdk():
    """SDK yalnız `AnthropicJudgeClient` içində, yalnız ilk çağırışda import olunur.

    Nəticə: `graders/` paketi SDK quraşdırılmadan qalxır və bütün test dəsti
    açarsız, şəbəkəsiz qaçır.
    """
    import subprocess
    import sys
    from pathlib import Path

    script = (
        "import sys\n"
        "from agentproof.graders import registry\n"
        "assert 'anthropic' not in sys.modules, 'anthropic SDK import olundu'\n"
        "assert 'requires_justification' in registry.names()\n"
        "print('ok')\n"
    )
    root = Path(__file__).resolve().parents[3]
    proc = subprocess.run(
        [sys.executable, "-c", script], cwd=root, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"

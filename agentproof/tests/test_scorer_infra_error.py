"""Scorer müqaviləsi: hədəfin İNFRASTRUKTUR xətası məzmun uğursuzluğu deyil.

Niyə bu ayrıca testdir. `full.jsonl`-in yarısından çoxu **inkar** assertion-udur
(`contains_none`, `regex_match` + `must_not_match`) — çünki bayat dəyərin
YOXLUĞU R6-nın əsas ölçüsüdür. Belə assertion BOŞ cavabda avtomatik keçir.
Hədəf rate-limit və ya timeout qaytardıqda cavab mətni boş olur; guard olmasa
sınmış qaçış **yaşıl** görünərdi — `O4 səssiz regressiya`-nın ən pis forması.

`AgentResponse.error` docstring-i bu müqaviləni artıq yazır; burada onun
kodda da tətbiq olunduğu yoxlanılır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from inspect_ai.util import store

from agentproof.runner.bridge import push_response
from agentproof.runner.scorer import grade_state
from agentproof.types import AgentResponse, Case


@dataclass
class _FakeState:
    metadata: dict[str, Any] = field(default_factory=dict)
    output: Any = None


NEGATIVE_CASES = [
    Case(id="neg-contains-none", input="q", grader="contains_none",
         expect={"none": ["30 days"]}),
    Case(id="neg-regex-invert", input="q", grader="regex_match",
         expect={"pattern": "not eligible", "must_not_match": True}),
    Case(id="neg-no-leak", input="q", grader="no_leak",
         expect={"secrets": ["nigar.a@example.az"]}),
]


@pytest.fixture(autouse=True)
def _clean_store():
    store().set("agentproof:responses", [])
    yield
    store().set("agentproof:responses", [])


@pytest.mark.parametrize("case", NEGATIVE_CASES, ids=lambda c: c.id)
def test_infra_error_is_skipped_not_passed(case: Case):
    push_response(AgentResponse(text="", error="rate_limit_error"))
    _, result = grade_state(_FakeState(metadata=case.to_dict()))
    assert result.skipped, (
        f"{case.id}: infrastruktur xətası olan boş cavab '{result.grader}' grader-indən "
        "KEÇDİ — bu, yalançı yaşıldır"
    )
    assert "rate_limit_error" in result.reason


def test_clean_empty_answer_still_reaches_the_grader():
    """Xəta YOXDURSA boş cavab qiymətləndirilir — guard həddindən geniş deyil."""
    case = Case(id="clean-empty", input="q", grader="contains_all", expect={"all": ["14"]})
    push_response(AgentResponse(text="", error=None))
    _, result = grade_state(_FakeState(metadata=case.to_dict()))
    assert not result.skipped
    assert not result.passed


def test_error_in_any_repeat_attempt_skips_the_case():
    """`--repeat N`: bir cəhd sınıbsa aqreqat nəticə də etibarsızdır."""
    case = Case(id="repeat-mixed", input="q", grader="contains_none",
                expect={"none": ["30 days"]})
    push_response(AgentResponse(text="The window is 14 days."))
    push_response(AgentResponse(text="", error="provider_not_initialize"))
    _, result = grade_state(_FakeState(metadata=case.to_dict()))
    assert result.skipped
    assert result.evidence["n_responses"] == 2


def test_successful_response_is_graded_normally():
    case = Case(id="ok", input="q", grader="contains_none", expect={"none": ["30 days"]})
    push_response(AgentResponse(text="The standard window is 14 calendar days."))
    _, result = grade_state(_FakeState(metadata=case.to_dict()))
    assert not result.skipped and result.passed

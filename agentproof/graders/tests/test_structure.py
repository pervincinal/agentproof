"""json_schema"""

from __future__ import annotations

from agentproof.graders import registry
from agentproof.graders.deterministic.structure import extract_json

SCHEMA = {
    "type": "object",
    "required": ["order_id", "eligible"],
    "properties": {
        "order_id": {"type": "string", "pattern": "^ORD-"},
        "eligible": {"type": "boolean"},
        "fee_percent": {"type": "number", "maximum": 100},
    },
}


def test_json_schema_passes_on_fenced_json(make_case, make_response):
    text = 'Nəticə:\n```json\n{"order_id": "ORD-1042", "eligible": true, "fee_percent": 15}\n```'
    result = registry.get("json_schema").grade(
        make_case("json_schema", {"schema": SCHEMA}), make_response(text=text)
    )
    assert result.passed
    assert result.evidence["parsed"]["order_id"] == "ORD-1042"


def test_json_schema_passes_on_bare_json(make_case, make_response):
    result = registry.get("json_schema").grade(
        make_case("json_schema", {"schema": SCHEMA}),
        make_response(text='{"order_id": "ORD-7", "eligible": false}'),
    )
    assert result.passed


def test_json_schema_fails_on_wrong_type(make_case, make_response):
    result = registry.get("json_schema").grade(
        make_case("json_schema", {"schema": SCHEMA}),
        make_response(text='{"order_id": "ORD-1042", "eligible": "bəli"}'),
    )
    assert not result.passed
    assert result.evidence["path"] == ["eligible"]
    assert result.reason


def test_json_schema_fails_on_missing_required_field(make_case, make_response):
    result = registry.get("json_schema").grade(
        make_case("json_schema", {"schema": SCHEMA}), make_response(text='{"eligible": true}')
    )
    assert not result.passed
    assert "order_id" in result.reason


def test_json_schema_fails_when_no_json_at_all(make_case, make_response):
    result = registry.get("json_schema").grade(
        make_case("json_schema", {"schema": SCHEMA}),
        make_response(text="Təəssüf ki, bu barədə məlumatım yoxdur."),
    )
    assert not result.passed
    assert "JSON" in result.reason


def test_extract_json_prefers_fence_over_stray_braces():
    payload, err = extract_json('bax {burada} ```json\n{"a": 1}\n``` son')
    assert err is None
    assert payload == {"a": 1}

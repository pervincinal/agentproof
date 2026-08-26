"""Struktur grader-i: json_schema."""

from __future__ import annotations

import json
import re
from typing import Any

import jsonschema

from agentproof.graders.base import grader, require
from agentproof.types import AgentResponse, Case, GradeResult

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> tuple[Any, str | None]:
    """Cavabdan JSON çıxar: əvvəl fence, sonra ilk balanslı obyekt/massiv."""
    for candidate in _FENCE.findall(text):
        try:
            return json.loads(candidate), None
        except ValueError:
            continue
    stripped = text.strip()
    try:
        return json.loads(stripped), None
    except ValueError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(stripped[start : end + 1]), None
            except ValueError:
                continue
    return None, "cavabda parse oluna bilən JSON yoxdur"


@grader
class JsonSchema:
    """Cavabdakı JSON `expect.schema`-ya uyğun olmalıdır.

    expect:
      schema: {...}   — JSON Schema (draft 2020-12), məcburi
    """

    name = "json_schema"
    kind = "deterministic"

    def grade(self, case: Case, response: AgentResponse) -> GradeResult:
        schema = require(case, "schema", self.name)
        payload, err = extract_json(response.text)
        if err:
            return GradeResult(
                passed=False,
                score=0.0,
                grader=self.name,
                reason=err,
                evidence={"answer_excerpt": response.text[:400]},
            )
        try:
            jsonschema.validate(payload, schema)  # type: ignore[arg-type]
        except jsonschema.ValidationError as e:
            return GradeResult(
                passed=False,
                score=0.0,
                grader=self.name,
                reason=f"sxem pozuntusu: {e.message}",
                evidence={
                    "path": list(e.absolute_path),
                    "validator": e.validator,
                    "parsed": payload,
                },
            )
        return GradeResult(
            passed=True,
            score=1.0,
            grader=self.name,
            reason="JSON sxemə uyğundur",
            evidence={"parsed": payload},
        )

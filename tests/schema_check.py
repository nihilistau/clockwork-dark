"""
Turn Schema Validator
=====================

Checks a canned model reply against the grammar the sampler actually enforces.

WHY THIS EXISTS. Every mock Storyteller in this suite used to emit a
``tool_calls`` array. The live turn schema
(``engine/lmstudio/schemas.py::storyteller_turn_schema``) sets
``additionalProperties: False`` and declares no such property, so with
structured output on that key is unsamplable -- no real model had ever sent one
or could. The suite was therefore green for months while exercising a channel
that did not exist in play, and the defect it hid was the largest one in the
project: a narration turn could not change the world.

A mock that can emit a shape the sampler cannot is not a stand-in for the model.
It is a second implementation of the game with different rules. So mocks build
their replies from the real schema and check them against the real schema.

WHY NOT ``jsonschema``. This project ships no schema library and adding one to
run tests would be a dependency for a hundred lines. More to the point, a
general validator would cover constructs the grammar does not, and could then
pass something the sampler would refuse -- which is the exact failure mode being
closed. The seven constructs below are all the turn schema uses.

Version: v0.1.0 [2026-08-14]
"""

from __future__ import annotations

from typing import Any


def _errors(instance: Any, schema: dict[str, Any], path: str) -> list[str]:
    """One node of validation, depth first. Returns problems, never raises."""
    problems: list[str] = []

    if "const" in schema:
        if instance != schema["const"]:
            problems.append(f"{path}: {instance!r} != const {schema['const']!r}")
        return problems

    if "enum" in schema:
        if instance not in schema["enum"]:
            problems.append(f"{path}: {instance!r} not in {schema['enum']}")
        return problems

    if "anyOf" in schema:
        if not any(not _errors(instance, branch, path) for branch in schema["anyOf"]):
            problems.append(
                f"{path}: matched none of the {len(schema['anyOf'])} branches"
            )
        return problems

    kind = schema.get("type")
    if kind == "object":
        if not isinstance(instance, dict):
            return [f"{path}: expected an object, got {type(instance).__name__}"]
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                problems.append(f"{path}: missing required '{key}'")
        for key, value in instance.items():
            if key in properties:
                problems.extend(_errors(value, properties[key], f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                problems.append(
                    f"{path}: '{key}' is not in the schema and "
                    "additionalProperties is false"
                )
    elif kind == "array":
        if not isinstance(instance, list):
            return [f"{path}: expected an array, got {type(instance).__name__}"]
        if len(instance) < schema.get("minItems", 0):
            problems.append(f"{path}: fewer than minItems {schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            problems.append(f"{path}: more than maxItems {schema['maxItems']}")
        for index, row in enumerate(instance):
            problems.extend(_errors(row, schema.get("items", {}), f"{path}[{index}]"))
    elif kind == "string":
        if not isinstance(instance, str):
            return [f"{path}: expected a string, got {type(instance).__name__}"]
        if len(instance) < schema.get("minLength", 0):
            problems.append(
                f"{path}: {len(instance)} chars, under minLength "
                f"{schema['minLength']}"
            )
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            problems.append(
                f"{path}: {len(instance)} chars, over maxLength "
                f"{schema['maxLength']}"
            )
    elif kind == "integer" and not isinstance(instance, int):
        problems.append(f"{path}: expected an integer")

    return problems


def validate(instance: Any, schema: dict[str, Any]) -> list[str]:
    """
    Check a value against a turn schema fragment.

    Args:
        instance: The candidate reply, or any sub-object of one.
        schema: The schema to check against -- the INNER ``schema`` of what
            ``storyteller_turn_schema`` returns, not the envelope.

    Returns:
        A list of human-readable problems. Empty means the sampler could have
        produced this.
    """
    return _errors(instance, schema, "$")


#: A NOTE ON RAISING. Callers RECORD what this returns rather than asserting on
#: it inside the mock. ``StorytellerAgent.run_turn`` catches everything around
#: the inference call and turns it into "the LLM is unavailable", so an
#: exception raised from inside an ``llm_fn`` is swallowed into a fallback
#: narration -- a guard that fails silently, which is the shape of the problem
#: it exists to catch. Collect, then assert in the test body.

__all__ = ["validate"]

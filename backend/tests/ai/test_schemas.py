"""Structured output: every role validates, and invalid output never escapes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai.errors import AIOutputInvalidError
from app.ai.provider import extract_json_payload
from app.ai.schemas import (
    ROLE_SCHEMAS,
    AutomationClassification,
    AutomationClass,
    ExtractionResult,
    Role,
    StepExplanation,
    StepUnderstanding,
)


def test_four_roles_have_schemas():
    assert set(ROLE_SCHEMAS) == {Role.EXTRACT, Role.UNDERSTAND, Role.EXPLAIN, Role.CLASSIFY}


def test_valid_extraction():
    result = ExtractionResult.model_validate(
        {"supplier": "AzLab Supplies", "items": ["calibration_kit"], "amount": 18400.0, "department": "Operations"}
    )
    assert result.supplier == "AzLab Supplies"
    assert result.insufficient_context is False


def test_valid_understanding():
    result = StepUnderstanding.model_validate(
        {"step_id": "stp_supplier", "step_name": "Identify Supplier", "purpose": "match to catalogue", "actor_role": "Procurement Specialist"}
    )
    assert result.actor_role == "Procurement Specialist"


def test_valid_explanation_requires_answer_and_bounded_confidence():
    result = StepExplanation.model_validate(
        {"summary": "short", "answer": "because POL-PR-07 applies", "confidence": 0.84, "evidence_refs": ["POL-PR-07"]}
    )
    assert result.confidence == 0.84
    with pytest.raises(ValidationError):
        StepExplanation.model_validate({"summary": "s", "answer": "a", "confidence": 1.4})
    with pytest.raises(ValidationError):
        StepExplanation.model_validate({"summary": "s", "answer": "   ", "confidence": 0.5})


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({"supplier": "X", "unexpected_field": 1})


@pytest.mark.parametrize("value", ["SAFE", "HUMAN_REVIEW", "HUMAN_REQUIRED"])
def test_canonical_classification_values(value):
    result = AutomationClassification.model_validate(
        {"automation_class": value, "reason": "r", "confidence": 0.5, "requires_approval": value == "HUMAN_REQUIRED"}
    )
    assert result.automation_class.value == value


@pytest.mark.parametrize("value", ["safe", "human review", "AUTOMATED", "REJECT", "", "SAFE_EXTRA"])
def test_invalid_classification_values_rejected(value):
    with pytest.raises(ValidationError):
        AutomationClassification.model_validate(
            {"automation_class": value, "reason": "r", "confidence": 0.5, "requires_approval": False}
        )


def test_human_required_must_require_approval():
    with pytest.raises(ValidationError):
        AutomationClassification.model_validate(
            {"automation_class": "HUMAN_REQUIRED", "reason": "r", "confidence": 0.9, "requires_approval": False}
        )


def test_enums_expose_canonical_wire_values():
    assert [item.value for item in AutomationClass] == ["SAFE", "HUMAN_REVIEW", "HUMAN_REQUIRED"]


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        'Here you go:\n{"a": 1}',
        '{"a": {"b": 2}, "c": 3} trailing prose',
    ],
)
def test_json_extraction_handles_varied_shapes(text):
    assert extract_json_payload(text) == extract_json_payload(text.strip())


def test_json_extraction_returns_none_for_prose():
    assert extract_json_payload("I cannot answer that.") is None
    assert extract_json_payload("") is None
    assert extract_json_payload(None) is None


def test_validate_raises_typed_error_for_wrong_schema(config):
    from app.ai.provider import build_provider
    from tests.ai.conftest import openai_text_handler

    provider = build_provider(config.primary, transport=__import__("httpx").MockTransport(openai_text_handler('{"wrong": true}')))
    with pytest.raises(AIOutputInvalidError) as excinfo:
        provider.complete("prompt", Role.EXTRACT)
    assert excinfo.value.code == "AI_OUTPUT_INVALID"
    assert excinfo.value.http_status == 422


def test_validate_raises_typed_error_for_non_object_json(config):
    import httpx

    from app.ai.provider import build_provider
    from tests.ai.conftest import openai_text_handler

    provider = build_provider(config.primary, transport=httpx.MockTransport(openai_text_handler("[1, 2, 3]")))
    with pytest.raises(AIOutputInvalidError):
        provider.complete("prompt", Role.EXPLAIN)
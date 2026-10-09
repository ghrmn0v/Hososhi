"""Contract regression tests.

The frozen v1 API contract is shared with Developer 1 and Developer 3. These
tests pin the shapes the AI layer produces, so a later refactor cannot quietly
change a field the frontend already binds to.
"""

from __future__ import annotations

import pytest

from app.ai.safety import POLICY_RULES_VERSION
from app.ai.schemas import (
    AutomationAnalyzeResponse,
    AutomationClass,
    AutomationStepResult,
    AutomationSummary,
    EvidenceItem,
    EvidenceListResponse,
    StepIntelligenceResponse,
)

from tests.ai.conftest import StubProvider, make_service

INTELLIGENCE_FIELDS = {
    "step_id",
    "question",
    "summary",
    "answer",
    "confidence",
    "evidence",
    "model",
    "generated_at",
    "fallback_used",
}
EVIDENCE_ITEM_FIELDS = {"ref", "type", "title", "snippet", "relevance", "date"}
ANALYZE_STEP_FIELDS = {"step_id", "name", "automation_class", "reason", "confidence", "requires_approval"}

GOOD_EXPLAIN = {
    "summary": "s",
    "answer": "Because POL-PR-07 sets the tolerance.",
    "confidence": 0.8,
    "evidence_refs": ["POL-PR-07"],
}


def test_intelligence_matches_the_frozen_shape(store):
    response = make_service(store, [StubProvider(payloads={"explain": GOOD_EXPLAIN})]).explain_step("stp_price")
    assert INTELLIGENCE_FIELDS <= set(response.model_dump())


def test_evidence_item_matches_the_frozen_shape():
    item = EvidenceItem(ref="POL-PR-07", type="policy", title="t", snippet="s", relevance=0.9, date="2025-11-01")
    assert set(item.model_dump()) == EVIDENCE_ITEM_FIELDS


def test_evidence_list_wraps_items_in_an_evidence_key(store):
    response = make_service(store, []).list_evidence(step_id="stp_price")
    payload = response.model_dump()
    assert "evidence" in payload
    assert isinstance(payload["evidence"], list)
    assert set(payload["evidence"][0]) == EVIDENCE_ITEM_FIELDS


def test_analyze_matches_the_frozen_shape(store):
    response = make_service(store, []).analyze_automation("wf_purchase_request")
    payload = response.model_dump()
    assert {"workflow_id", "policy_rules_version", "summary", "steps"} <= set(payload)
    assert payload["policy_rules_version"] == POLICY_RULES_VERSION
    assert ANALYZE_STEP_FIELDS <= set(payload["steps"][0])


def test_analyze_summary_keys_are_lowercase_snake(store):
    response = make_service(store, []).analyze_automation("wf_purchase_request")
    assert set(response.summary.model_dump()) == {"safe", "human_review", "human_required"}


def test_class_wire_values_use_underscores(store):
    """SAFE / HUMAN_REVIEW / HUMAN_REQUIRED on the wire, spaces only in the UI."""
    response = make_service(store, []).analyze_automation("wf_purchase_request")
    for step in response.steps:
        assert " " not in step.automation_class.value
        assert step.automation_class.value in {"SAFE", "HUMAN_REVIEW", "HUMAN_REQUIRED"}


def test_requires_approval_is_true_exactly_when_human_required(store):
    response = make_service(store, []).analyze_automation("wf_purchase_request")
    for step in response.steps:
        assert step.requires_approval == (step.automation_class is AutomationClass.HUMAN_REQUIRED)


def test_confidence_is_a_unit_interval_on_every_payload(store):
    intelligence = make_service(store, [StubProvider(payloads={"explain": GOOD_EXPLAIN})]).explain_step("stp_price")
    analysis = make_service(store, []).analyze_automation("wf_purchase_request")
    assert 0.0 <= intelligence.confidence <= 1.0
    for item in intelligence.evidence:
        assert 0.0 <= item.relevance <= 1.0
    for step in analysis.steps:
        assert 0.0 <= step.confidence <= 1.0


def test_generated_at_is_iso_utc(store):
    response = make_service(store, []).analyze_automation("wf_purchase_request")
    assert response.generated_at.endswith("Z")
    assert "T" in response.generated_at


def test_endpoint_8_response_rejects_an_unknown_class():
    with pytest.raises(Exception):
        AutomationStepResult(step_id="x", automation_class="TOTALLY_SAFE", reason="r", confidence=0.5, requires_approval=False)


def test_response_models_forbid_extra_fields():
    with pytest.raises(Exception):
        EvidenceListResponse(evidence=[], returned=0, unexpected=True)
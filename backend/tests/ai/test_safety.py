"""Safety classification. The model may advise; the rubric enforces (AI-05, SAFE-*)."""

from __future__ import annotations

import pytest

from app.ai.config import ProviderConfig
from app.ai.safety import (
    POLICY_RULES_VERSION,
    apply_amount_threshold,
    classify_safety,
    deterministic_class,
)
from app.ai.schemas import AutomationClass, Role

from tests.ai.conftest import StubProvider, make_config, make_service


APPROVAL_STEP = {
    "id": "stp_approval",
    "name": "Manager Approval",
    "type": "approval",
    "actor_role": "Department Manager",
    "description": "The department manager reviews the request and approves or rejects the spend.",
}

PO_STEP = {
    "id": "stp_po",
    "name": "Create Purchase Order",
    "type": "execution",
    "actor_role": "Procurement Specialist",
    "description": "Raise the purchase order with the approved supplier once approval is recorded.",
}

EXTRACT_STEP = {
    "id": "stp_extract",
    "name": "Extract Request Information",
    "type": "extraction",
    "actor_role": "Procurement Specialist",
    "description": "Read the submitted request and extract supplier, items, amount and department.",
}

PRICE_STEP = {
    "id": "stp_price",
    "name": "Verify Price",
    "type": "verification",
    "actor_role": "Procurement Specialist",
    "description": "Compare the requested unit price against the catalogue price.",
}

DECISION_STEP = {
    "id": "stp_decisions",
    "name": "Search Historical Decisions",
    "type": "retrieval",
    "actor_role": "Procurement Specialist",
    "description": "Look for earlier decisions and exceptions relevant to this request.",
}


def test_policy_rules_version_is_pinned():
    assert POLICY_RULES_VERSION == "safety-rules-v1"


@pytest.mark.parametrize("step", [APPROVAL_STEP, PO_STEP])
@pytest.mark.parametrize("proposed", list(AutomationClass))
def test_financial_steps_are_never_safe_whichever_class_the_model_proposes(step, proposed):
    """An LLM must never be able to mark an approval or PO step SAFE."""
    decision = classify_safety(step, model_class=proposed, model_reason="model says so", model_confidence=0.99)
    assert decision.automation_class is AutomationClass.HUMAN_REQUIRED
    assert decision.requires_approval is True
    if proposed is not AutomationClass.HUMAN_REQUIRED:
        assert decision.safety_override is True
        assert "safety override" in (decision.override_reason or "").lower()


def test_amount_threshold_overrides_a_safe_proposal():
    decision = classify_safety(PRICE_STEP, model_class=AutomationClass.SAFE, model_confidence=0.95)
    assert decision.automation_class is AutomationClass.SAFE
    escalated = apply_amount_threshold(decision, amount=18_400.0, threshold=2000.0)
    assert escalated.automation_class is AutomationClass.HUMAN_REQUIRED
    assert escalated.requires_approval is True
    assert escalated.safety_override is True
    assert "amount override" in (escalated.override_reason or "").lower()


def test_amount_below_threshold_is_not_overridden():
    decision = classify_safety(PRICE_STEP, model_class=AutomationClass.SAFE, model_confidence=0.9)
    assert apply_amount_threshold(decision, amount=640.0, threshold=2000.0) is decision


def test_conflicting_evidence_blocks_safe():
    decision = classify_safety(
        EXTRACT_STEP, model_class=AutomationClass.SAFE, model_confidence=0.95, conflicting_evidence=True
    )
    assert decision.automation_class is AutomationClass.HUMAN_REVIEW
    assert decision.safety_override is True


def test_insufficient_context_is_never_safe():
    for proposed in AutomationClass:
        decision = classify_safety(EXTRACT_STEP, model_class=proposed, insufficient_context=True)
        assert decision.automation_class is not AutomationClass.SAFE


def test_judgement_step_cannot_be_safe():
    decision = classify_safety(DECISION_STEP, model_class=AutomationClass.SAFE, model_confidence=0.99)
    assert decision.automation_class is AutomationClass.HUMAN_REVIEW
    assert decision.safety_override is True


def test_read_only_step_is_safe_when_the_model_agrees():
    decision = classify_safety(
        EXTRACT_STEP, model_class=AutomationClass.SAFE, model_reason="pure extraction", model_confidence=0.93
    )
    assert decision.automation_class is AutomationClass.SAFE
    assert decision.requires_approval is False
    assert decision.safety_override is False


def test_unknown_step_type_is_not_auto_safe():
    step = {
        "id": "stp_x",
        "name": "Reconcile Supplier Records",
        "type": "custom",
        "actor_role": "Buyer",
        "description": "Compare supplier master records against the catalogue.",
    }
    decision = classify_safety(step, model_class=AutomationClass.SAFE, model_confidence=0.9)
    assert decision.automation_class is AutomationClass.HUMAN_REVIEW


def test_a_contract_step_is_financial_not_just_unknown():
    step = {"id": "stp_y", "name": "Negotiate Contract Terms", "type": "custom", "actor_role": "Buyer", "description": "d"}
    assert classify_safety(step, model_class=AutomationClass.SAFE).automation_class is AutomationClass.HUMAN_REQUIRED


def test_deterministic_classification_without_any_model():
    assert deterministic_class(APPROVAL_STEP).automation_class is AutomationClass.HUMAN_REQUIRED
    assert deterministic_class(PO_STEP).automation_class is AutomationClass.HUMAN_REQUIRED
    assert deterministic_class(EXTRACT_STEP).automation_class is AutomationClass.HUMAN_REVIEW


def test_safety_is_enforced_through_the_service(store):
    """End-to-end: a model that answers SAFE for every step is still overruled."""
    provider = StubProvider(
        payloads={
            Role.CLASSIFY: {
                "step_id": "stp_approval",
                "automation_class": "SAFE",
                "reason": "I think it is fine",
                "confidence": 0.99,
                "evidence_refs": ["POL-PR-01"],
                "requires_approval": False,
            }
        }
    )
    service = make_service(store, [provider])
    result = service.analyze_automation("wf_purchase_request")

    by_id = {step.step_id: step for step in result.steps}
    assert by_id["stp_approval"].automation_class is AutomationClass.HUMAN_REQUIRED
    assert by_id["stp_approval"].requires_approval is True
    assert by_id["stp_po"].automation_class is AutomationClass.HUMAN_REQUIRED
    assert result.summary.human_required >= 2


def test_summary_counts_match_the_steps(store):
    provider = StubProvider(
        payloads={
            Role.CLASSIFY: {
                "automation_class": "HUMAN_REVIEW",
                "reason": "r",
                "confidence": 0.5,
                "evidence_refs": [],
                "requires_approval": False,
            }
        }
    )
    service = make_service(store, [provider])
    result = service.analyze_automation("wf_purchase_request")
    total = result.summary.safe + result.summary.human_review + result.summary.human_required
    assert total == len(result.steps) == len(store.steps)


def test_amounts_are_enforced_by_the_service(store):
    provider = StubProvider(
        payloads={
            Role.CLASSIFY: {
                "automation_class": "SAFE",
                "reason": "r",
                "confidence": 0.8,
                "evidence_refs": [],
                "requires_approval": False,
            }
        }
    )
    service = make_service(store, [provider])
    result = service.analyze_automation("wf_purchase_request", amounts={"stp_extract": 5000.0})
    by_id = {step.step_id: step for step in result.steps}
    assert by_id["stp_extract"].automation_class is AutomationClass.HUMAN_REQUIRED
    assert by_id["stp_extract"].override_reason


def test_every_step_gets_class_reason_and_confidence(store):
    provider = StubProvider(
        payloads={
            Role.CLASSIFY: {
                "automation_class": "SAFE",
                "reason": "deterministic",
                "confidence": 0.8,
                "evidence_refs": [],
                "requires_approval": False,
            }
        }
    )
    service = make_service(store, [provider])
    for step in service.analyze_automation("wf_purchase_request").steps:
        assert step.automation_class in set(AutomationClass)
        assert step.reason.strip()
        assert 0.0 <= step.confidence <= 1.0


def test_unconfigured_provider_falls_back_without_failing(store):
    config = make_config(
        primary=ProviderConfig(name="groq", model="m", api_key=None, base_url="https://api.groq.com/openai/v1")
    )
    service = make_service(store, [], config=config)
    result = service.analyze_automation("wf_purchase_request")
    assert result.fallback_used is True
    assert result.model == "deterministic-fallback"
    assert len(result.steps) == len(store.steps)
    assert result.summary.human_required >= 2
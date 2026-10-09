"""Scenario tests for the AI layer.

TEST-006  conflicting policy
TEST-007  ambiguous historical decision
plus the AI-01…AI-10 items that need a running pipeline rather than a unit.
"""

from __future__ import annotations

import pytest

from app.ai.pipeline import _has_conflicting_evidence
from app.ai.schemas import AutomationClass, Role

from tests.ai.conftest import StubProvider, make_service

# --------------------------------------------------------------------------- #
# TEST-006 - conflicting policy
# --------------------------------------------------------------------------- #

CONFLICTING_POLICY_EXPLANATION = {
    "step_id": "stp_policy",
    "question": "Why does this step exist?",
    "summary": "Two policies disagree about the approval threshold.",
    "answer": (
        "The policy check exists because two policies disagree. POL-PR-01 requires manager approval "
        "above 2000 AZN, while POL-PR-22 allows purchases up to 2000 AZN to be converted directly. "
        "Hososhi does not pick one silently; the conflict must be resolved by a person."
    ),
    "confidence": 0.42,
    "evidence_refs": ["POL-PR-01", "POL-PR-22"],
    "conflicts": ["POL-PR-01", "POL-PR-22"],
}

CONFLICTING_POLICY_CLASSIFICATION = {
    "step_id": "stp_policy",
    "automation_class": "SAFE",
    "reason": "just a lookup",
    "confidence": 0.94,
    "evidence_refs": ["POL-PR-01", "POL-PR-22"],
    "requires_approval": False,
}


def test_policy_step_has_contradictory_evidence_in_context(store):
    context = make_service(store, []).retrieve("stp_policy")
    policies = {item.ref: item.snippet.lower() for item in context.evidence if item.type == "policy"}
    assert "POL-PR-01" in policies and "POL-PR-22" in policies
    assert _has_conflicting_evidence(context) is True


def test_test006_explanation_states_the_conflict_and_cites_both_policies(store):
    response = make_service(
        store, [StubProvider(payloads={Role.EXPLAIN: CONFLICTING_POLICY_EXPLANATION})]
    ).explain_step("stp_policy")

    cited = {item.ref for item in response.evidence}
    assert {"POL-PR-01", "POL-PR-22"} <= cited
    assert response.confidence < 0.6, "confidence must drop when evidence conflicts"
    assert response.conflicts, "the conflict must be surfaced, not hidden"
    assert set(response.conflicts) == {"POL-PR-01", "POL-PR-22"}
    assert "do not pick one silently" in response.answer.lower() or "does not" in response.answer.lower()


def test_test006_step_is_at_least_human_review(store):
    """Even when the model says SAFE with 0.94 confidence."""
    result = make_service(
        store, [StubProvider(payloads={Role.CLASSIFY: CONFLICTING_POLICY_CLASSIFICATION})]
    ).analyze_automation("wf_purchase_request")

    by_id = {step.step_id: step for step in result.steps}
    policy_step = by_id["stp_policy"]
    assert policy_step.automation_class in (
        AutomationClass.HUMAN_REVIEW,
        AutomationClass.HUMAN_REQUIRED,
    )
    assert policy_step.safety_override is True
    assert "conflict" in policy_step.reason.lower()


# --------------------------------------------------------------------------- #
# TEST-007 - ambiguous historical decision
# --------------------------------------------------------------------------- #

AMBIGUOUS_DECISION_EXPLANATION = {
    "step_id": "stp_decisions",
    "question": "Why does this step exist?",
    "summary": "Past decisions on this matter were never resolved.",
    "answer": (
        "This step exists because DEC-118 records three consecutive price-variance breaches and is "
        "marked unresolved, and DEC-121 is also unresolved over whether small purchases need manager "
        "approval. With no settled precedent, the step cannot be automated away."
    ),
    "confidence": 0.31,
    "evidence_refs": ["DEC-118", "DEC-121"],
}


def test_decision_step_has_unresolved_history_in_context(store):
    context = make_service(store, []).retrieve("stp_decisions")
    refs = {item.ref for item in context.evidence}
    assert {"DEC-118", "DEC-121"} <= refs
    assert _has_conflicting_evidence(context) is False  # no policy conflict, only ambiguity


def test_test007_surfaces_ambiguity_with_low_confidence(store):
    response = make_service(
        store, [StubProvider(payloads={Role.EXPLAIN: AMBIGUOUS_DECISION_EXPLANATION})]
    ).explain_step("stp_decisions")

    cited = {item.ref for item in response.evidence}
    assert {"DEC-118", "DEC-121"} <= cited
    assert response.confidence < 0.5
    assert "unresolved" in response.answer.lower()
    assert response.confidence < 0.84  # materially below a confident answer


def test_test007_decision_step_cannot_be_safe(store):
    provider = StubProvider(
        payloads={
            Role.CLASSIFY: {
                "step_id": "stp_decisions",
                "automation_class": "SAFE",
                "reason": "just a search",
                "confidence": 0.97,
                "evidence_refs": ["DEC-118"],
                "requires_approval": False,
            }
        }
    )
    result = make_service(store, [provider]).analyze_automation("wf_purchase_request")
    by_id = {step.step_id: step for step in result.steps}
    assert by_id["stp_decisions"].automation_class is not AutomationClass.SAFE
    assert by_id["stp_decisions"].safety_override is True


ORPHAN_EXPLANATION = {
    "step_id": "stp_orphan",
    "question": "Why does this step exist?",
    "summary": "No evidence was retrieved for this step.",
    "answer": "The provided context is insufficient to explain why this step exists.",
    "confidence": 0.0,
    "evidence_refs": [],
    "insufficient_context": True,
}


# --------------------------------------------------------------------------- #
# AI-06 / grounding under weak evidence
# --------------------------------------------------------------------------- #


def test_empty_evidence_context_yields_an_honest_insufficient_answer(store):
    """A step with no evidence at all must not produce a confident answer."""
    store.steps = [
        {
            "id": "stp_orphan",
            "name": "Orphan Step",
            "type": "verification",
            "actor_role": "Procurement Specialist",
            "description": "A step with nothing in the dataset that speaks to it.",
            "keywords": ["orphan"],
            "department": None,
        }
    ]
    store.policies, store.decisions, store.incidents, store.events = [], [], [], []

    service = make_service(store, [StubProvider(payloads={Role.EXPLAIN: ORPHAN_EXPLANATION})])
    response = service.explain_step("stp_orphan")

    # The model asked for the honest answer; the layer still refuses to over-claim.
    assert response.insufficient_context is True
    assert response.confidence == 0.0
    assert response.evidence == []
    assert "insufficient" in response.answer.lower()
    assert response.fallback_used is False  # the model answered, so nothing fell back


def test_orphaned_step_is_not_classified_safe(store):
    store.steps = [
        {
            "id": "stp_orphan",
            "name": "Orphan Step",
            "type": "verification",
            "actor_role": "Procurement Specialist",
            "description": "A step with nothing in the dataset that speaks to it.",
            "keywords": ["orphan"],
            "department": None,
        }
    ]
    store.policies, store.decisions, store.incidents, store.events = [], [], [], []

    result = make_service(
        store,
        [
            StubProvider(
                payloads={
                    Role.CLASSIFY: {
                        "automation_class": "SAFE",
                        "reason": "looks simple",
                        "confidence": 0.99,
                        "evidence_refs": [],
                        "requires_approval": False,
                    }
                }
            )
        ],
    ).analyze_automation("wf_purchase_request")

    assert result.steps[0].automation_class is not AutomationClass.SAFE
    assert result.steps[0].safety_override is True


def test_confidence_is_always_in_range(store):
    response = make_service(store, [StubProvider(payloads={Role.EXPLAIN: AMBIGUOUS_DECISION_EXPLANATION})]).explain_step(
        "stp_price"
    )
    assert 0.0 <= response.confidence <= 1.0
    assert response.model


@pytest.mark.parametrize("step_id", ["stp_price", "stp_policy", "stp_approval", "stp_po"])
def test_demo_steps_all_produce_an_answer(store, step_id):
    response = make_service(store, [StubProvider(payloads={Role.EXPLAIN: CONFLICTING_POLICY_EXPLANATION})]).explain_step(
        step_id
    )
    assert response.answer.strip()
    assert response.step_id == step_id
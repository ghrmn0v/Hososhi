"""Automation safety classification.

The rubric is deterministic and reviewable. The model may advise a class, but
the rules in this module are what the product enforces: a step that is
irreversible or a financial commitment can never be reported as SAFE because a
model said so.

Rubric (safety-rules-v1), evaluated in this order
-------------------------------------------------
1.  A step that commits money, issues a binding document, or is otherwise
    irreversible is HUMAN_REQUIRED.
2.  A step whose outcome depends on interpreting ambiguous or conflicting
    history, policy or judgement is at least HUMAN_REVIEW.
3.  A step whose evidence is insufficient is never SAFE; lowest defensible
    class is HUMAN_REVIEW.
4.  A step that only reads, extracts, matches or compares against a reference
    source, with no financial commitment, no judgement and sufficient evidence,
    may be SAFE.
5.  Anything else is not proven deterministic, so it is HUMAN_REVIEW.
6.  The model's answer is an input to this rubric, never a substitute for it:
    a model answer can only ever make the class stricter, never more
    permissive.
"""

from __future__ import annotations

from dataclasses import dataclass

from .schemas import AutomationClass

POLICY_RULES_VERSION = "safety-rules-v1"

# Any of these markers in the step name/description/type means the step is
# about committing money or issuing a binding artefact.
FINANCIAL_COMMITMENT_MARKERS = (
    "approval",
    "approve",
    "authorise",
    "authorize",
    "sign off",
    "sign-off",
    "purchase order",
    "po creation",
    "payment",
    "contract",
    "commit",
    "spend",
)

IRREVERSIBLE_MARKERS = (
    "purchase order",
    "payment",
    "contract",
    "issue order",
    "raise the po",
    "dispatch",
    "submit to supplier",
)

JUDGEMENT_MARKERS = (
    "historical decision",
    "past decision",
    "exception",
    "judgement",
    "judgment",
    "escalate",
    "interpret",
    "negotiate",
    "reconcile",
)

READ_ONLY_STEP_TYPES = {
    "trigger",
    "extraction",
    "lookup",
    "verification",
    "policy_check",
    "retrieval",
    "analysis",
}


@dataclass(frozen=True)
class SafetyDecision:
    automation_class: AutomationClass
    reason: str
    confidence: float
    requires_approval: bool
    safety_override: bool = False
    override_reason: str | None = None

    @classmethod
    def of(
        cls,
        automation_class: AutomationClass,
        reason: str,
        confidence: float,
        *,
        safety_override: bool = False,
        override_reason: str | None = None,
    ) -> "SafetyDecision":
        return cls(
            automation_class=automation_class,
            reason=reason,
            confidence=confidence,
            requires_approval=automation_class is AutomationClass.HUMAN_REQUIRED,
            safety_override=safety_override,
            override_reason=override_reason,
        )


def _text(step: dict) -> str:
    return " ".join(
        str(step.get(key) or "")
        for key in ("name", "description", "type", "actor_role")
    ).lower()


def classify_safety(
    step: dict,
    *,
    model_class: AutomationClass | None = None,
    model_reason: str = "",
    model_confidence: float = 0.0,
    insufficient_context: bool = False,
    conflicting_evidence: bool = False,
) -> SafetyDecision:
    """Apply the rubric. `model_*` are advisory inputs only."""
    haystack = _text(step)
    step_type = str(step.get("type") or "").lower()
    actor_role = str(step.get("actor_role") or "").lower()

    # Rule 1: financial commitment / irreversible, performed or authorised by a human.
    financial = any(marker in haystack for marker in FINANCIAL_COMMITMENT_MARKERS)
    irreversible = any(marker in haystack for marker in IRREVERSIBLE_MARKERS)
    human_actor = bool(actor_role) and not actor_role.startswith("system")

    if financial or irreversible:
        reason = (
            "Step commits a financial or irreversible business action"
            + (f" performed by role '{step.get('actor_role')}'" if human_actor else "")
            + ". Human authorisation is mandatory."
        )
        if model_class is not AutomationClass.HUMAN_REQUIRED:
            return SafetyDecision.of(
                AutomationClass.HUMAN_REQUIRED,
                reason,
                confidence=max(model_confidence, 0.95),
                safety_override=model_class is not None,
                override_reason=(
                    f"safety override: model proposed {model_class.value}" if model_class else None
                ),
            )
        return SafetyDecision.of(AutomationClass.HUMAN_REQUIRED, model_reason or reason, model_confidence)

    # Rule 2: judgement or conflicting/ambiguous history.
    judgement = any(marker in haystack for marker in JUDGEMENT_MARKERS)
    if judgement or conflicting_evidence:
        reason_parts = []
        if judgement:
            reason_parts.append("the step requires interpretation of judgement or history")
        if conflicting_evidence:
            reason_parts.append("retrieved evidence conflicts")
        if insufficient_context:
            reason_parts.append("available evidence is insufficient to verify determinism")
        reason = (
            "Human review required: "
            + "; ".join(reason_parts)
            + ". A model proposal must be confirmed by a person."
        )
        ceiling = 0.5 if insufficient_context else 0.7
        if model_class is AutomationClass.SAFE:
            return SafetyDecision.of(
                AutomationClass.HUMAN_REVIEW,
                reason,
                confidence=min(model_confidence, ceiling),
                safety_override=True,
                override_reason=(
                    "safety override: insufficient context may never be SAFE"
                    if insufficient_context
                    else "safety override: model proposed SAFE for a judgement/conflicting step"
                ),
            )
        chosen = model_class if model_class in (AutomationClass.HUMAN_REVIEW, AutomationClass.HUMAN_REQUIRED) else AutomationClass.HUMAN_REVIEW
        return SafetyDecision.of(chosen, model_reason or reason, model_confidence or 0.6)

    # Rule 3: insufficient evidence is never SAFE.
    if insufficient_context:
        reason = (
            "Available evidence is insufficient to verify that this step is deterministic, "
            "so it is not eligible for unattended execution."
        )
        return SafetyDecision.of(
            AutomationClass.HUMAN_REVIEW,
            model_reason or reason,
            min(model_confidence, 0.5),
            safety_override=model_class is not None,
            override_reason=(
                "safety override: insufficient context may never be SAFE" if model_class else None
            ),
        )

    # Rule 4: deterministic, read-only.
    if step_type in READ_ONLY_STEP_TYPES and model_class is AutomationClass.SAFE:
        return SafetyDecision.of(
            AutomationClass.SAFE,
            model_reason or "Deterministic, verifiable and read-only; no financial commitment.",
            model_confidence or 0.8,
        )

    # Rule 5: anything else is not proven deterministic.
    reason = (
        "No rule marks this step as a deterministic read-only operation, "
        "so it is not eligible for unattended execution."
    )
    if model_class in (AutomationClass.HUMAN_REVIEW, AutomationClass.HUMAN_REQUIRED):
        return SafetyDecision.of(model_class, model_reason or reason, model_confidence or 0.6)
    return SafetyDecision.of(
        AutomationClass.HUMAN_REVIEW,
        reason,
        confidence=0.55,
        safety_override=model_class is not None,
        override_reason="safety override: only deterministic read-only steps may be SAFE",
    )


def apply_amount_threshold(
    decision: SafetyDecision,
    *,
    amount: float | None,
    threshold: float = 2000.0,
    currency: str = "AZN",
) -> SafetyDecision:
    """Business rule owned by the plan: a large amount forces HUMAN_REQUIRED.

    This is the deterministic backend rule Developer 1 also applies. It exists
    here so the AI layer cannot under-classify an expensive request even when
    the model is confident.
    """
    if amount is None or amount <= threshold:
        return decision
    if decision.automation_class is AutomationClass.HUMAN_REQUIRED:
        return decision
    return SafetyDecision.of(
        AutomationClass.HUMAN_REQUIRED,
        f"Request amount {amount} {currency} exceeds the {threshold} {currency} approval threshold, "
        "which requires explicit human authorisation.",
        confidence=0.99,
        safety_override=True,
        override_reason=(
            f"amount override: model/engine proposed {decision.automation_class.value}"
        ),
    )


def deterministic_class(step: dict) -> SafetyDecision:
    """Rubric-only classification, used when no provider is available."""
    return classify_safety(step)
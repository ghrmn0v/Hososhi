"""Discovery service: raw workflow events -> stable Workflow + Step records.

Events are grouped per purchase request (entity sequence), then repeated action
patterns are consolidated into one Step per distinct action, ordered by the
median position at which that action occurs across sequences.
"""

from collections import defaultdict
from datetime import datetime
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Step, Workflow, WorkflowEvent

# Canonical action -> (step key, display name, actor role, type, description).
# "submit_request" is deliberately absent: it is the trigger that opens a sequence,
# not a step of the discovered workflow, so the workflow resolves to 7 steps.
ACTION_CATALOG: dict[str, tuple[str, str, str, str, str]] = {
    "extract_fields": (
        "stp_extract",
        "Extract Request Information",
        "Procurement Specialist",
        "extraction",
        "Line items, quantities and cost centres are read from the submitted request.",
    ),
    "match_supplier": (
        "stp_supplier",
        "Identify Supplier",
        "Procurement Specialist",
        "lookup",
        "Submitted supplier hint is matched against the approved supplier catalogue.",
    ),
    "verify_price": (
        "stp_price",
        "Verify Price",
        "Procurement Specialist",
        "verification",
        "Requested unit price is compared against the contracted catalogue price.",
    ),
    "evaluate_policy": (
        "stp_policy",
        "Check Company Policy",
        "Procurement Specialist",
        "verification",
        "Request is evaluated against procurement policies and approval thresholds.",
    ),
    "search_decisions": (
        "stp_history",
        "Search Historical Decisions",
        "Procurement Specialist",
        "lookup",
        "Prior decisions and incidents are searched for similar past requests.",
    ),
    "approve_request": (
        "stp_approval",
        "Manager Approval",
        "Department Manager",
        "decision",
        "A manager reviews the request and decides whether to approve it.",
    ),
    "create_po": (
        "stp_po",
        "Create Purchase Order",
        "Procurement Specialist",
        "creation",
        "An approved request is converted into a purchase order for the supplier.",
    ),
}

# Static fallback classification, used only while Developer 2's AI layer is absent.
# The backend re-derives this server-side on every run and applies its own overrides;
# a client-supplied class is never trusted.
STATIC_CLASS_MAP: dict[str, tuple[str, str]] = {
    "stp_extract": ("SAFE", "Deterministic field extraction from a submitted request."),
    "stp_supplier": ("HUMAN_REVIEW", "Catalogue matching is fuzzy; a human confirms the match."),
    "stp_price": ("SAFE", "Deterministic comparison against contracted catalogue price."),
    "stp_policy": ("SAFE", "Deterministic rule evaluation against seeded policies."),
    "stp_history": ("SAFE", "Read-only lookup of prior decisions and incidents."),
    "stp_approval": ("HUMAN_REQUIRED", "Spending commitment requires human judgement."),
    "stp_po": ("SAFE", "Deterministic creation, permitted only after an approved record."),
}

CLASS_TO_DISPLAY = {
    "SAFE": "SAFE",
    "HUMAN_REVIEW": "HUMAN REVIEW",
    "HUMAN_REQUIRED": "HUMAN REQUIRED",
}

# Reverse view of ACTION_CATALOG, keyed by step id.
STEP_CATALOG: dict[str, tuple[str, str, str, str]] = {
    entry[0]: (entry[1], entry[2], entry[3], entry[4]) for entry in ACTION_CATALOG.values()
}

WORKFLOW_ID = "wf_purchase_request"
WORKFLOW_NAME = "Purchase Request Processing"
DISCOVERY_METHOD = "event-sequence-clustering"


def group_sequences(db: Session) -> list[list[WorkflowEvent]]:
    """One sequence per request_id, each ordered by timestamp."""
    events = db.scalars(select(WorkflowEvent).order_by(WorkflowEvent.timestamp, WorkflowEvent.id)).all()
    by_request: dict[str, list[WorkflowEvent]] = defaultdict(list)
    for event in events:
        if event.request_id:
            by_request[event.request_id].append(event)

    sequences = []
    for request_id in sorted(by_request):
        sequences.append(sorted(by_request[request_id], key=lambda e: (e.timestamp, e.id)))
    return sequences


def _sequence_steps(sequence: list[WorkflowEvent]) -> list[str]:
    """Distinct canonical step keys for one sequence, in observed order."""
    steps: list[str] = []
    for event in sequence:
        entry = ACTION_CATALOG.get(event.action)
        if entry and entry[0] not in steps:
            steps.append(entry[0])
    return steps


def consolidate(sequences: list[list[WorkflowEvent]]) -> list[str]:
    """Collapse repeated actions into one step each, then order them.

    Primary ordering is the median observed position across sequences, which is
    robust to a minority of sequences disagreeing. Pairwise precedence votes and
    first-observed position only break ties, because a net pairwise score is
    inherently biased towards early steps.
    """
    per_sequence = [_sequence_steps(sequence) for sequence in sequences]
    all_steps = sorted({step for steps in per_sequence for step in steps})
    if not all_steps:
        return []

    positions: dict[str, list[int]] = defaultdict(list)
    score = {step: 0 for step in all_steps}
    first_seen: dict[str, int] = {}

    for steps in per_sequence:
        for index, step in enumerate(steps):
            positions[step].append(index)
            first_seen.setdefault(step, index)
        for a_index, a in enumerate(steps):
            for b in steps[a_index + 1:]:
                score[a] += 1
                score[b] -= 1

    return sorted(
        all_steps,
        key=lambda step: (
            median(positions[step]),
            -score[step],
            first_seen[step],
            step,
        ),
    )


def compute_confidence(sequences: list[list[WorkflowEvent]], ordered_steps: list[str]) -> float:
    """Share of sequences that follow the discovered step order, plus coverage."""
    if not sequences:
        return 0.0
    target_index = {step: index for index, step in enumerate(ordered_steps)}

    agreeing = 0
    for sequence in sequences:
        seen: list[str] = []
        for event in sequence:
            entry = ACTION_CATALOG.get(event.action)
            if entry and entry[0] not in seen:
                seen.append(entry[0])
        if len(seen) < 2:
            continue
        positions = [target_index[s] for s in seen if s in target_index]
        if positions == sorted(positions):
            agreeing += 1

    usable = sum(1 for s in sequences if len(s) > 1)
    if usable == 0:
        return 0.0
    return round(agreeing / usable, 4)


def discover_and_persist(db: Session) -> Workflow:
    """Run discovery and store the result. Idempotent: re-running rebuilds rows."""
    sequences = group_sequences(db)
    ordered_steps = consolidate(sequences)
    confidence = compute_confidence(sequences, ordered_steps)

    workflow = db.get(Workflow, WORKFLOW_ID)
    if workflow is None:
        workflow = Workflow(id=WORKFLOW_ID, name=WORKFLOW_NAME)
        db.add(workflow)
    db.query(Step).filter(Step.workflow_id == WORKFLOW_ID).delete()

    workflow.category = "procurement"
    workflow.description = (
        "End-to-end procurement workflow reconstructed from observed system events, "
        "not from a documented process."
    )
    workflow.status = "discovered"
    workflow.discovery_method = DISCOVERY_METHOD
    workflow.confidence = confidence
    workflow.event_count = sum(len(s) for s in sequences)
    workflow.date_range = _date_range(sequences)

    previous_step_id: str | None = None
    for index, step_key in enumerate(ordered_steps, start=1):
        display_name, actor_role, step_type, description = STEP_CATALOG[step_key]
        automation_class, reason = STATIC_CLASS_MAP[step_key]
        db.add(
            Step(
                id=step_key,
                workflow_id=WORKFLOW_ID,
                name=display_name,
                order_index=index,
                actor_role=actor_role,
                step_type=step_type,
                description=description,
                automation_class=automation_class,
                automation_reason=reason,
                confidence=confidence,
                estimated_manual_minutes=0.0,
                depends_on=[previous_step_id] if previous_step_id else [],
            )
        )
        previous_step_id = step_key

    db.commit()
    db.refresh(workflow)
    return workflow


def _date_range(sequences: list[list[WorkflowEvent]]) -> dict:
    stamps = [e.timestamp for s in sequences for e in s if e.timestamp]
    if not stamps:
        return {}
    return {
        "start": min(stamps).date().isoformat(),
        "end": max(stamps).date().isoformat(),
    }
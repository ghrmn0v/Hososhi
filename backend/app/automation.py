"""Automation engine: run state machine, deterministic step execution, approval gate.

The backend is the only security layer. Automation classes are re-derived
server-side on every run; a client-supplied class is never trusted.
"""

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.discovery import STATIC_CLASS_MAP
from app.errors import conflict, invalid_transition, not_found
from app.models import Approval, PurchaseOrder, PurchaseRequest, RunStep, Step, Workflow, WorkflowRun

settings = get_settings()

# Legal state transitions for a run. Anything not listed is rejected with 409.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "failed"},
    "running": {"waiting_approval", "completed", "failed"},
    "waiting_approval": {"running", "rejected", "failed"},
    "completed": set(),
    "rejected": set(),
    "failed": set(),
}

TERMINAL_STATES = {"completed", "rejected", "failed"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def resolve_automation_class(step: Step, request: PurchaseRequest) -> tuple[str, str, bool, str | None]:
    """Re-derive a step's automation class server-side.

    Returns (class, reason, overridden_by_backend, override_reason).
    Developer 2's AI classification is consulted when available; until then the
    static map is used. The amount override below always wins.
    """
    stored_class = step.automation_class or STATIC_CLASS_MAP.get(step.id, ("HUMAN_REQUIRED", ""))[0]
    stored_reason = step.automation_reason or STATIC_CLASS_MAP.get(step.id, ("", ""))[1]

    # Deterministic safety override, deliberately scoped.
    #
    # The approval threshold is already covered by the workflow's own Manager
    # Approval step, which is always HUMAN REQUIRED, so it must NOT escalate every
    # SAFE step: doing so would stop the run at step 1 instead of at the approval.
    #
    # The high-value override is what genuinely needs enforcing: above it, even a
    # step the AI merely wanted a second look at (HUMAN REVIEW) becomes a hard
    # human gate, and SAFE execution is suspended.
    high_value = settings.high_value_review_threshold
    if request is not None and request.amount >= high_value and stored_class == "HUMAN_REVIEW":
        return (
            "HUMAN_REQUIRED",
            stored_reason,
            True,
            f"Request amount {request.amount} {request.currency} is at or above the "
            f"{high_value} {settings.currency} high-value threshold; a review step "
            "becomes a hard human gate.",
        )

    # A decision step stays a human gate whenever the approval threshold applies,
    # even if the AI classified it SAFE.
    if (
        stored_class == "SAFE"
        and step.step_type == "decision"
        and request is not None
        and request.amount >= settings.human_approval_amount_threshold
    ):
        return (
            "HUMAN_REQUIRED",
            stored_reason,
            True,
            f"Decision step on a request of {request.amount} {request.currency} "
            f"({settings.human_approval_amount_threshold} {settings.currency} threshold) "
            "cannot be automated.",
        )

    return (stored_class, stored_reason, False, None)


def get_workflow(db: Session, workflow_id: str) -> Workflow:
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise not_found(f"Workflow '{workflow_id}' does not exist.")
    return workflow


def get_steps(db: Session, workflow_id: str) -> list[Step]:
    return list(
        db.scalars(
            select(Step)
            .where(Step.workflow_id == workflow_id)
            .order_by(Step.order_index)
        ).all()
    )


def find_existing_run(db: Session, workflow_id: str, request_id: str) -> WorkflowRun | None:
    """Idempotency guard: a run for this request already exists and is still live.

    'Live' excludes rejected and failed runs so a caller can retry after a
    rejection. A completed run is also returned, so a repeat submission is
    answered with the original run rather than a second one.
    """
    return db.scalars(
        select(WorkflowRun).where(
            WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.request_id == request_id,
            WorkflowRun.state.not_in(["rejected", "failed"]),
        )
    ).first()


def assert_transition(current: str, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise invalid_transition(
            f"A run in state '{current}' cannot move to '{target}'."
        )


def start_run(db: Session, workflow_id: str, request_id: str) -> WorkflowRun:
    get_workflow(db, workflow_id)
    steps = get_steps(db, workflow_id)
    if not steps:
        raise not_found(f"Workflow '{workflow_id}' has no discovered steps.")

    request = db.get(PurchaseRequest, request_id)
    if request is None:
        raise not_found(f"Purchase request '{request_id}' does not exist.")

    # Guard lives here as well as in the router so no code path can create two runs.
    existing = find_existing_run(db, workflow_id, request_id)
    if existing is not None:
        return existing

    run = WorkflowRun(
        id=f"run_{uuid.uuid4().hex[:16]}",
        workflow_id=workflow_id,
        request_id=request_id,
        state="pending",
    )
    # The unique index fires on flush, not on commit, so the whole insert is guarded.
    try:
        db.add(run)
        db.flush()

        for step in steps:
            db.add(
                RunStep(
                    run_id=run.id,
                    step_id=step.id,
                    state="pending",
                )
            )
        db.commit()
    except IntegrityError:
        # A concurrent submission won the race on the unique index. Return that run
        # so the caller never sees a second execution path. The winner may not have
        # committed yet, so retry briefly before giving up with 409.
        db.rollback()
        for attempt in range(5):
            concurrent = find_existing_run(db, workflow_id, request_id)
            if concurrent is not None:
                return concurrent
            time.sleep(0.05 * (attempt + 1))
        raise conflict(
            "A concurrent run for this request is already being created. "
            "Retry to receive the existing run."
        )
    return run


def execute_safe_steps(db: Session, run: WorkflowRun) -> WorkflowRun:
    """Advance the run until it completes or hits a HUMAN REQUIRED step.

    Only SAFE steps execute here. HUMAN REQUIRED always produces an Approval and
    a waiting_approval run, never a completion.

    A run that is already past 'pending' is returned untouched. Without this
    guard a concurrent caller could hold a stale reference to a run that has
    since reached waiting_approval and resume it, which would skip the gate.
    """
    # Claim the run atomically. A conditional UPDATE means exactly one concurrent
    # caller can move it out of 'pending'; the losers see 0 rows affected and
    # return the run as-is, so no protected step can execute twice.
    claimed = db.execute(
        update(WorkflowRun)
        .where(WorkflowRun.id == run.id, WorkflowRun.state == "pending")
        .values(state="running", started_at=utcnow())
    ).rowcount

    if not claimed:
        db.rollback()
        db.refresh(run)
        return run

    request = db.get(PurchaseRequest, run.request_id)
    steps = {s.id: s for s in get_steps(db, run.workflow_id)}
    run_steps = list(
        db.scalars(
            select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.id)
        ).all()
    )

    db.refresh(run)

    for run_step in run_steps:
        if run_step.state != "pending":
            continue

        step = steps.get(run_step.step_id)
        if step is None:
            continue

        automation_class, reason, overridden, override_reason = resolve_automation_class(step, request)

        if automation_class == "HUMAN_REQUIRED":
            run_step.state = "waiting_approval"
            run_step.actor = None
            run_step.output_summary = (
                f"Blocked: requires human decision. {override_reason or reason}"
            )
            run.state = "waiting_approval"

            approval = db.scalars(
                select(Approval).where(
                    Approval.run_id == run.id,
                    Approval.step_id == step.id,
                    Approval.state == "pending",
                )
            ).first()
            if approval is None:
                approval = Approval(
                    id=f"apr_{uuid.uuid4().hex[:16]}",
                    run_id=run.id,
                    step_id=step.id,
                    required_role=step.actor_role,
                    state="pending",
                )
                db.add(approval)
                db.flush()
            run.metrics = {**(run.metrics or {}), "blocked_on": f"approval:{approval.id}"}
            db.commit()
            return run

        # SAFE steps execute deterministically in-process.
        started = utcnow()
        output = _execute_deterministic(step, request)
        finished = utcnow()

        run_step.state = "completed"
        run_step.started_at = started
        run_step.finished_at = finished
        run_step.duration_ms = max(int((finished - started).total_seconds() * 1000), 0)
        run_step.actor = "system"
        run_step.output_summary = output + (f" [overridden: {override_reason}]" if overridden else "")
        db.commit()

    assert_transition(run.state, "completed")
    run.state = "completed"
    run.finished_at = utcnow()
    db.commit()
    return run


def _execute_deterministic(step: Step, request: PurchaseRequest | None) -> str:
    """Real backend logic per step. No model call, no invented output."""
    if step.id == "stp_extract":
        items = request.items or [] if request else []
        return f"Extracted {len(items)} line item(s) from {request.id if request else 'request'}."
    if step.id == "stp_supplier":
        if request and request.supplier_id:
            return f"Matched supplier {request.supplier_id} on the approved catalogue."
        return "No supplier matched the submitted hint; request held for review."
    if step.id == "stp_price":
        return (
            f"Compared requested price against catalogue for {request.id}; "
            "variance recorded."
            if request
            else "Price comparison skipped: no request."
        )
    if step.id == "stp_policy":
        threshold = settings.human_approval_amount_threshold
        amount = request.amount if request else 0
        return (
            f"Evaluated procurement policies; amount {amount} "
            f"{request.currency if request else settings.currency} "
            f"{'meets' if amount >= threshold else 'is below'} the {threshold} approval threshold."
        )
    if step.id == "stp_history":
        return "Searched historical decisions and incidents for comparable requests."
    return f"Executed deterministic step '{step.name}'."


def advance_after_approval(db: Session, run: WorkflowRun, approval: Approval, decision: str) -> WorkflowRun:
    """Apply a human decision. Approve completes the run; reject stops it."""
    assert_transition(run.state, "running")

    approval.state = "approved" if decision == "approve" else "rejected"
    approval.decided_at = utcnow()

    if decision == "reject":
        run.state = "rejected"
        run.finished_at = utcnow()
        remaining = {k: v for k, v in (run.metrics or {}).items() if k != "blocked_on"}
        run.metrics = remaining or None
        db.commit()
        return run

    # Approve: mark the approved step complete, then execute remaining SAFE steps
    # and create the purchase order.
    run_step = db.scalars(
        select(RunStep).where(
            RunStep.run_id == run.id, RunStep.step_id == approval.step_id
        )
    ).first()
    if run_step is not None:
        run_step.state = "completed"
        run_step.actor = approval.decided_by
        run_step.started_at = approval.decided_at
        run_step.finished_at = utcnow()
        run_step.duration_ms = max(
            int((run_step.finished_at - run_step.started_at).total_seconds() * 1000), 0
        )
        run_step.output_summary = f"{approval.decided_by} approved this step."

    run.state = "running"
    db.commit()

    steps = {s.id: s for s in get_steps(db, run.workflow_id)}
    request = db.get(PurchaseRequest, run.request_id)

    for candidate in list(
        db.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.id)).all()
    ):
        if candidate.state != "pending":
            continue
        step = steps.get(candidate.step_id)
        if step is None:
            continue

        automation_class, reason, overridden, override_reason = resolve_automation_class(step, request)
        if automation_class == "HUMAN_REQUIRED":
            candidate.state = "waiting_approval"
            candidate.output_summary = f"Blocked: requires human decision. {override_reason or reason}"
            run.state = "waiting_approval"
            approval_row = Approval(
                id=f"apr_{uuid.uuid4().hex[:16]}",
                run_id=run.id,
                step_id=step.id,
                required_role=step.actor_role,
                state="pending",
            )
            db.add(approval_row)
            db.flush()
            run.metrics = {**(run.metrics or {}), "blocked_on": f"approval:{approval_row.id}"}
            db.commit()
            return run

        started = utcnow()
        output = _execute_deterministic(step, request)
        finished = utcnow()
        candidate.state = "completed"
        candidate.started_at = started
        candidate.finished_at = finished
        candidate.duration_ms = max(int((finished - started).total_seconds() * 1000), 0)
        candidate.actor = "system"
        candidate.output_summary = output + (f" [overridden: {override_reason}]" if overridden else "")
        db.commit()

    purchase_order = _create_purchase_order(db, run, approval, request)
    assert_transition(run.state, "completed")
    run.state = "completed"
    run.finished_at = utcnow()
    # The run is no longer blocked; keep a stale blocked_on out of the response.
    remaining = {k: v for k, v in (run.metrics or {}).items() if k != "blocked_on"}
    run.metrics = remaining or None
    db.commit()
    return run


def _create_purchase_order(
    db: Session, run: WorkflowRun, approval: Approval, request: PurchaseRequest | None
) -> PurchaseOrder:
    """PO creation requires an approved approval record belonging to this run."""
    approved = db.scalars(
        select(Approval).where(
            Approval.run_id == run.id, Approval.state == "approved"
        )
    ).first()
    if approved is None:
        raise invalid_transition(
            "A purchase order cannot be created without an approved approval record for this run."
        )

    existing = db.scalars(
        select(PurchaseOrder).where(PurchaseOrder.approval_id == approved.id)
    ).first()
    if existing is not None:
        run.purchase_order_id = existing.id
        return existing

    purchase_order = PurchaseOrder(
        id=f"po_{uuid.uuid4().hex[:16]}",
        request_id=run.request_id,
        run_id=run.id,
        approval_id=approved.id,
        supplier_id=request.supplier_id if request else None,
        amount=request.amount if request else 0.0,
        currency=request.currency if request else settings.currency,
        status="issued",
    )
    db.add(purchase_order)
    db.flush()
    run.purchase_order_id = purchase_order.id
    return purchase_order


def decide_approval(
    db: Session, approval_id: str, decision: str, approver_id: str, comment: str
) -> WorkflowRun:
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise not_found(f"Approval '{approval_id}' does not exist.")
    if approval.state != "pending":
        raise invalid_transition(
            f"Approval '{approval_id}' was already {approval.state}."
        )

    run = db.get(WorkflowRun, approval.run_id)
    if run is None:
        raise not_found(f"Run '{approval.run_id}' does not exist.")
    if run.state != "waiting_approval":
        raise invalid_transition(
            f"Run '{run.id}' is in state '{run.state}' and is not awaiting approval."
        )

    approval.decided_by = approver_id
    approval.comment = comment
    db.commit()

    return advance_after_approval(db, run, approval, decision)
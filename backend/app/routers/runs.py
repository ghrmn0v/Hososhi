"""Automation run, run polling, approvals, and measured results."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import automation, metrics
from app.db import get_db
from app.errors import not_found
from app.models import Approval, RunStep, WorkflowRun
from app.schemas import (
    ApprovalDecisionRequest,
    AutomationRunRequest,
    ResultsResponse,
    RunResponse,
    RunStepResponse,
)

router = APIRouter(prefix="/api/v1", tags=["automation"])


def _run_step_responses(db: Session, run: WorkflowRun) -> list[RunStepResponse]:
    steps = {s.id: s for s in automation.get_steps(db, run.workflow_id)}
    rows = list(db.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.id)).all())

    pending_approval_by_step = {}
    for approval in db.scalars(select(Approval).where(Approval.run_id == run.id)).all():
        if approval.state == "pending":
            pending_approval_by_step[approval.step_id] = approval.id

    out = []
    for row in rows:
        step = steps.get(row.step_id)
        out.append(
            RunStepResponse(
                step_id=row.step_id,
                name=step.name if step else row.step_id,
                automation_class=step.automation_class if step else None,
                state=row.state,
                started_at=row.started_at,
                finished_at=row.finished_at,
                duration_ms=row.duration_ms,
                actor=row.actor,
                output_summary=row.output_summary,
                approval_id=pending_approval_by_step.get(row.step_id),
            )
        )
    return out


def _run_response(db: Session, run: WorkflowRun) -> RunResponse:
    return RunResponse(
        run_id=run.id,
        workflow_id=run.workflow_id,
        request_id=run.request_id,
        state=run.state,
        started_at=run.started_at,
        finished_at=run.finished_at,
        steps=_run_step_responses(db, run),
        blocked_on=(run.metrics or {}).get("blocked_on"),
        purchase_order_id=run.purchase_order_id,
        metrics=run.metrics or None,
    )


@router.post("/workflows/{workflow_id}/automation/run", response_model=RunResponse)
def start_automation_run(
    workflow_id: str, payload: AutomationRunRequest, db: Session = Depends(get_db)
) -> RunResponse:
    existing = automation.find_existing_run(db, workflow_id, payload.request_id)
    if existing is not None:
        # Idempotent: return the live run untouched rather than executing again.
        return _run_response(db, existing)

    run = automation.start_run(db, workflow_id, payload.request_id)
    run = automation.execute_safe_steps(db, run)
    db.refresh(run)
    return _run_response(db, run)


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str, db: Session = Depends(get_db)) -> RunResponse:
    run = db.get(WorkflowRun, run_id)
    if run is None:
        raise not_found(f"Run '{run_id}' does not exist.")
    return _run_response(db, run)


@router.post("/approvals/{approval_id}", response_model=RunResponse)
def decide(
    approval_id: str, payload: ApprovalDecisionRequest, db: Session = Depends(get_db)
) -> RunResponse:
    run = automation.decide_approval(
        db, approval_id, payload.decision, payload.approver_id, payload.comment
    )
    db.refresh(run)
    return _run_response(db, run)


@router.get("/results/{run_id}", response_model=ResultsResponse)
def results(run_id: str, db: Session = Depends(get_db)) -> ResultsResponse:
    run = db.get(WorkflowRun, run_id)
    if run is None:
        raise not_found(f"Run '{run_id}' does not exist.")
    return metrics.build_results(db, run)
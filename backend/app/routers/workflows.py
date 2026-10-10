"""Read endpoints: workflows, workflow detail, single step, dashboard."""

from fastapi import APIRouter, Depends, Path
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.discovery import CLASS_TO_DISPLAY
from app.errors import not_found
from app.models import (
    PurchaseRequest,
    Step,
    Supplier,
    Workflow,
    WorkflowEvent,
    WorkflowRun,
)
from app.schemas import (
    DashboardAutomationCounts,
    DashboardOpportunity,
    DashboardRecentWorkflow,
    DashboardResponse,
    DiscoveryInfo,
    StepResponse,
    WorkflowDetailResponse,
    WorkflowListResponse,
    WorkflowSummary,
    StepIntelligenceResponse,
    EvidenceListResponse,
    EvidenceItem,
    AnalyzeResponse,
    StepClassification,
    AutomationClass,
    DashboardAutomationCounts,
)
from app.ai.retrieval import retrieve_context
from app.ai.prompts import build_prompt
from app.ai.safety import classify_safety, apply_amount_threshold
from app.ai.schemas import EvidenceItem as AIEvidenceItem
from app.ai import default_service, Role

router = APIRouter(prefix="/api/v1", tags=["workflows"])
settings = get_settings()


def _counts_for_steps(steps: list[Step]) -> DashboardAutomationCounts:
    counts = DashboardAutomationCounts()
    for step in steps:
        if step.automation_class == "SAFE":
            counts.safe += 1
        elif step.automation_class == "HUMAN_REVIEW":
            counts.human_review += 1
        elif step.automation_class == "HUMAN_REQUIRED":
            counts.human_required += 1
    return counts


def _automation_counts(db: Session, workflow_id: str) -> DashboardAutomationCounts:
    return _counts_for_steps(
        list(
            db.scalars(
                select(Step).where(Step.workflow_id == workflow_id).order_by(Step.order_index)
            ).all()
        )
    )


def _discovery_info(workflow: Workflow) -> DiscoveryInfo:
    date_range = workflow.date_range or {}
    start, end = date_range.get("start"), date_range.get("end")
    return DiscoveryInfo(
        method=workflow.discovery_method,
        event_count=workflow.event_count,
        date_range=[start, end] if start and end else None,
        confidence=workflow.confidence,
    )


def _step_response(step: Step) -> StepResponse:
    return StepResponse(
        id=step.id,
        workflow_id=step.workflow_id,
        name=step.name,
        order=step.order_index,
        type=step.step_type,
        description=step.description,
        actor_role=step.actor_role,
        automation_class=CLASS_TO_DISPLAY.get(step.automation_class or "", None),
        automation_reason=step.automation_reason,
        confidence=step.confidence,
        estimated_manual_minutes=step.estimated_manual_minutes,
        depends_on=step.depends_on or [],
    )


@router.get("/workflows", response_model=WorkflowListResponse)
def list_workflows(db: Session = Depends(get_db)) -> WorkflowListResponse:
    workflows = list(db.scalars(select(Workflow).order_by(Workflow.name)).all())
    return WorkflowListResponse(
        workflows=[
            WorkflowSummary(
                id=w.id,
                name=w.name,
                category=w.category,
                description=w.description,
                discovered=True,
                discovery=_discovery_info(w),
                step_count=db.scalar(
                    select(func.count()).select_from(Step).where(Step.workflow_id == w.id)
                ) or 0,
                automation=_automation_counts(db, w.id),
                status=w.status,
            )
            for w in workflows
        ]
    )


@router.get("/workflows/{workflow_id}", response_model=WorkflowDetailResponse)
def get_workflow(workflow_id: str, db: Session = Depends(get_db)) -> WorkflowDetailResponse:
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise not_found(f"Workflow '{workflow_id}' does not exist.")
    steps = list(
        db.scalars(
            select(Step).where(Step.workflow_id == workflow_id).order_by(Step.order_index)
        ).all()
    )
    return WorkflowDetailResponse(
        id=workflow.id,
        name=workflow.name,
        category=workflow.category,
        description=workflow.description,
        discovery=_discovery_info(workflow),
        steps=[_step_response(s) for s in steps],
        status=workflow.status,
    )


@router.get("/workflows/{workflow_id}/steps/{step_id}", response_model=StepResponse)
def get_step(workflow_id: str, step_id: str, db: Session = Depends(get_db)) -> StepResponse:
    step = db.get(Step, step_id)
    if step is None or step.workflow_id != workflow_id:
        raise not_found(f"Step '{step_id}' does not exist in workflow '{workflow_id}'.")
    return _step_response(step)


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(db: Session = Depends(get_db)) -> DashboardResponse:
    workflow_rows = list(db.scalars(select(Workflow).order_by(Workflow.name)).all())
    primary = workflow_rows[0] if workflow_rows else None

    steps_count = db.scalar(select(func.count()).select_from(Step)) or 0
    events_count = db.scalar(select(func.count()).select_from(WorkflowEvent)) or 0
    requests_count = db.scalar(select(func.count()).select_from(PurchaseRequest)) or 0

    opportunities: list[DashboardOpportunity] = []
    automation = DashboardAutomationCounts()
    if primary is not None:
        steps = list(
            db.scalars(
                select(Step).where(Step.workflow_id == primary.id).order_by(Step.order_index)
            ).all()
        )
        automation = _counts_for_steps(steps)
        for step in steps:
            if step.automation_class == "SAFE":
                opportunities.append(
                    DashboardOpportunity(
                        step_id=step.id,
                        workflow_id=primary.id,
                        step_name=step.name,
                        reason=step.automation_reason or "",
                        potential_manual_minutes=(
                            step.estimated_manual_minutes
                            if step.estimated_manual_minutes
                            else None
                        ),
                        source="none",
                    )
                )

    recent = []
    for run in db.scalars(
        select(WorkflowRun).order_by(WorkflowRun.started_at.desc().nullslast()).limit(5)
    ).all():
        recent.append(
            DashboardRecentWorkflow(
                workflow_id=run.workflow_id,
                name=primary.name if primary else run.workflow_id,
                status=run.state,
                updated_at=run.finished_at or run.started_at,
            )
        )

    return DashboardResponse(
        workflows_discovered=len(workflow_rows),
        steps_discovered=steps_count,
        total_purchase_requests=requests_count,
        events_analysed=events_count,
        automation=automation,
        automation_opportunities=opportunities,
        recent_workflows=recent,
        dataset_name=settings.dataset_name,
        dataset_is_synthetic=True,
    )


# --- 6. GET /api/v1/workflows/{workflow_id}/steps/{step_id}/intelligence ---
@router.get(
    "/workflows/{workflow_id}/steps/{step_id}/intelligence",
    response_model=StepIntelligenceResponse,
)
def workflow_step_intelligence(
    workflow_id: str = Path(..., description="Workflow identifier"),
    step_id: str = Path(..., description="Step identifier"),
    db: Session = Depends(get_db),
) -> StepIntelligenceResponse:
    """Return evidence-backed explanation for why a step exists."""
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise not_found(f"Workflow '{workflow_id}' does not exist.")

    step = db.get(Step, step_id)
    if step is None or step.workflow_id != workflow_id:
        raise not_found(f"Step '{step_id}' does not exist in workflow '{workflow_id}'.")

    # Retrieve relevant context for this step
    context = retrieve_context(step_id)

    # Build prompt and call AI service
    prompt = build_prompt(Role.EXPLAIN, context)
    result = default_service().explain_step(step_id)

    # Map AI service response to existing schema
    evidence = [
        EvidenceItem(
            id=item.ref,
            type=item.type,
            title=item.title,
            snippet=item.snippet,
            relevance=item.relevance,
            date=item.date,
        )
        for item in result.evidence
    ]

    return StepIntelligenceResponse(
        step_id=step_id,
        workflow_id=workflow_id,
        step_name=step.name,
        question=result.question,
        summary=result.summary,
        answer=result.answer,
        confidence=result.confidence,
        evidence=evidence,
        model=result.model,
        measured_at=result.generated_at,
        fallback_used=result.fallback_used,
        insufficient_context=result.insufficient_context,
        assumptions=result.assumptions,
        conflicts=result.conflicts,
    )


# --- 7. GET /api/v1/workflows/{workflow_id}/evidence ---
@router.get(
    "/workflows/{workflow_id}/evidence",
    response_model=EvidenceListResponse,
)
def workflow_evidence_list(
    workflow_id: str = Path(..., description="Workflow identifier"),
    step_id: str | None = None,
    evidence_type: str | None = None,
    db: Session = Depends(get_db),
) -> EvidenceListResponse:
    """Return evidence list for a workflow step, optionally filtered by step_id and evidence_type."""
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise not_found(f"Workflow '{workflow_id}' does not exist.")

    # Retrieve evidence from AI service
    result = default_service().list_evidence(step_id=step_id, evidence_type=evidence_type)

    # Apply bounds: return at most 50 items
    items = result.evidence[:50]
    # Map AI EvidenceItem (with ref) → API EvidenceItem (with id) per frozen contract
    api_items = []
    for ev in items:
        api_ev = EvidenceItem.model_construct(id=ev.ref, type=ev.type, title=ev.title, snippet=ev.snippet, relevance=ev.relevance, date=ev.date)
        api_items.append(api_ev.model_dump())

    return EvidenceListResponse(
        workflow_id=workflow_id,
        evidence=api_items,
        count=len(api_items),
    )


# --- 8. POST /api/v1/workflows/{workflow_id}/automation/analyze ---
@router.post(
    "/workflows/{workflow_id}/automation/analyze",
    response_model=AnalyzeResponse,
)
def workflow_automation_analyze(
    workflow_id: str = Path(..., description="Workflow identifier"),
    step_ids: list[str] | None = None,
    db: Session = Depends(get_db),
) -> AnalyzeResponse:
    """Return automation classification for each step, with backend safety enforcement."""
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise not_found(f"Workflow '{workflow_id}' does not exist.")

    # Retrieve steps from database; filter by step_ids if provided
    query = select(Step).where(Step.workflow_id == workflow_id)
    if step_ids:
        query = query.where(Step.id.in_(step_ids))
    steps = list(db.scalars(query).all())

    # Classify each step using the safety rubric
    classifications: list[StepClassification] = []
    counts = DashboardAutomationCounts()

    for step in steps:
        # Apply safety classification
        safety_decision = classify_safety(step)

        counts.safe += 1 if safety_decision.automation_class == AutomationClass.SAFE else 0
        counts.human_review += 1 if safety_decision.automation_class == AutomationClass.HUMAN_REVIEW else 0
        counts.human_required += 1 if safety_decision.automation_class == AutomationClass.HUMAN_REQUIRED else 0

        classifications.append(
            StepClassification(
                step_id=step.id,
                step_name=step.name,
                automation_class=safety_decision.automation_class,
                reason=safety_decision.reason,
                overridden_by_backend=safety_decision.safety_override,
                override_reason=safety_decision.override_reason,
            )
        )

    return AnalyzeResponse(
        workflow_id=workflow_id,
        classifications=classifications,
        counts=counts,
    )
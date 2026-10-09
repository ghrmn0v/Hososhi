"""Every request/response model for the Hososhi API.

This file is the single source of truth for the v1 contract (frozen 10:45).
Developer 2 (AI routes) and Developer 3 (frontend) build against these models.
Do not change a shape after the freeze without telling all three developers.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# --- Shared primitives ---

AutomationClass = Literal["SAFE", "HUMAN REVIEW", "HUMAN REQUIRED"]
AutomationClassEnum = Literal["SAFE", "HUMAN_REVIEW", "HUMAN_REQUIRED"]
RunState = Literal[
    "pending", "running", "waiting_approval", "completed", "rejected", "failed"
]
StepState = Literal[
    "pending", "running", "completed", "waiting_approval", "skipped", "failed"
]
ApprovalState = Literal["pending", "approved", "rejected"]
MetricSource = Literal[
    "replayed_from_dataset", "measured_in_this_run", "none"
]
ErrorCode = Literal[
    "VALIDATION_ERROR",
    "NOT_FOUND",
    "INVALID_STATE_TRANSITION",
    "AI_PROVIDER_UNAVAILABLE",
    "AI_OUTPUT_INVALID",
    "RATE_LIMITED",
    "INTERNAL_ERROR",
]


# --- 1. GET /health ---


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


# --- 2. GET /dashboard ---


class DashboardAutomationCounts(BaseModel):
    safe: int = 0
    human_review: int = 0
    human_required: int = 0


class DashboardOpportunity(BaseModel):
    step_id: str
    workflow_id: str
    step_name: str
    reason: str
    potential_manual_minutes: float | None = None
    source: MetricSource = "none"


class DashboardRecentWorkflow(BaseModel):
    workflow_id: str
    name: str
    status: str
    updated_at: datetime | None = None


class DashboardResponse(BaseModel):
    workflows_discovered: int
    steps_discovered: int
    total_purchase_requests: int
    events_analysed: int
    automation: DashboardAutomationCounts
    automation_opportunities: list[DashboardOpportunity] = []
    recent_workflows: list[DashboardRecentWorkflow] = []
    dataset_name: str
    dataset_is_synthetic: bool = True


# --- 3. GET /workflows ---


class DiscoveryInfo(BaseModel):
    method: str
    event_count: int
    date_range: list[str] | None = None
    confidence: float


class WorkflowSummary(BaseModel):
    id: str
    name: str
    category: str
    description: str
    discovered: bool = True
    discovery: DiscoveryInfo
    step_count: int
    automation: DashboardAutomationCounts
    status: str


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowSummary]


# --- 4. GET /workflows/{workflow_id} ---


class StepResponse(BaseModel):
    id: str
    workflow_id: str
    name: str
    order: int
    type: str
    description: str
    actor_role: str
    automation_class: AutomationClass | None = None
    automation_reason: str | None = None
    confidence: float
    estimated_manual_minutes: float
    depends_on: list[str] = []


class WorkflowDetailResponse(BaseModel):
    id: str
    name: str
    category: str
    description: str
    discovery: DiscoveryInfo
    steps: list[StepResponse]
    status: str


# --- 5. GET /workflows/{workflow_id}/steps/{step_id} ---
# Same shape as a single entry of WorkflowDetailResponse.steps.


# --- 6. GET /workflows/{wid}/steps/{sid}/intelligence (Developer 2) ---


class EvidenceItem(BaseModel):
    id: str
    type: Literal["policy", "decision", "incident", "event"]
    title: str
    snippet: str
    relevance: float | None = None
    date: str | None = None
    metadata: dict[str, Any] = {}


class StepIntelligenceResponse(BaseModel):
    step_id: str
    workflow_id: str
    step_name: str
    question: str = "Why does this step exist?"
    answer: str
    evidence: list[EvidenceItem] = []
    model: str | None = None
    provider: str | None = None
    measured_at: datetime | None = None


# --- 7. GET /workflows/{wid}/evidence (Developer 2) ---


class EvidenceListResponse(BaseModel):
    workflow_id: str
    evidence: list[EvidenceItem]
    count: int


# --- 8. POST /workflows/{wid}/automation/analyze (Developer 2) ---


class AnalyzeRequest(BaseModel):
    request_id: str | None = None
    steps: list[str] | None = None


class StepClassification(BaseModel):
    step_id: str
    step_name: str
    automation_class: AutomationClassEnum
    reason: str
    overridden_by_backend: bool = False
    override_reason: str | None = None


class AnalyzeResponse(BaseModel):
    workflow_id: str
    classifications: list[StepClassification]
    counts: DashboardAutomationCounts


# --- 9. POST /workflows/{wid}/automation/run ---


class AutomationRunRequest(BaseModel):
    request_id: str


class RunStepResponse(BaseModel):
    step_id: str
    name: str
    automation_class: AutomationClassEnum | None = None
    state: StepState
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    actor: str | None = None
    output_summary: str | None = None
    approval_id: str | None = None


class RunResponse(BaseModel):
    run_id: str
    workflow_id: str
    request_id: str
    state: RunState
    started_at: datetime | None = None
    finished_at: datetime | None = None
    steps: list[RunStepResponse] = []
    blocked_on: str | None = None
    purchase_order_id: str | None = None
    metrics: dict[str, Any] | None = None


# --- 10. GET /runs/{run_id} ---
# Same shape as the 9 response, including live approval state.


# --- 11. POST /approvals/{approval_id} ---


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    approver_id: str
    comment: str = ""


# --- 12. GET /results/{run_id} ---


class MetricBlock(BaseModel):
    label: str
    source: MetricSource
    total_duration_ms: float | None = None
    manual_steps: int | None = None
    human_decisions: int | None = None
    automation_rate: float | None = None
    errors: int | None = None
    # What interval total_duration_ms actually spans, stated so the UI and the
    # submission text cannot describe it as something it is not.
    measurement_scope: str | None = None


class ResultsDelta(BaseModel):
    duration_ms: float | None = None
    duration_percent: float | None = None
    human_interventions: int | None = None


class ResultsResponse(BaseModel):
    run_id: str
    workflow_id: str
    measured_at: datetime | None = None
    measurement_method: str
    runs_count: int
    baseline: MetricBlock
    ai_assisted: MetricBlock
    delta: ResultsDelta
    is_measured: bool = False
    # True only when both sides measure the same interval and may be differenced.
    # False means the two durations are NOT interchangeable and no speedup claim
    # may be derived from delta.
    is_comparable: bool = False
    comparability_note: str | None = None
    ai_call_count: int | None = None


# --- 13. GET /meta ---


class MetaResponse(BaseModel):
    product: str
    version: str
    dataset_name: str
    dataset_is_synthetic: bool = True
    dataset_seed: int
    event_count: int
    purchase_request_count: int
    data_generated_by: Literal["deterministic_synthetic_generator"] = "deterministic_synthetic_generator"
    ai_provider: str
    ai_model: str | None = None
    ai_fallback_active: bool = False
    measurement_method: str
    notes: str | None = None


# --- Error envelope (all non-2xx responses) ---


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool = False
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
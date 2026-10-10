"""SQLAlchemy models for Hososhi. All dataset rows produced here are synthetic."""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(80))
    department: Mapped[str] = mapped_column(String(80))
    manager_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str] = mapped_column(String(160))

    requests: Mapped[list["PurchaseRequest"]] = relationship(back_populates="employee")


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(80))
    risk_tier: Mapped[str] = mapped_column(String(20))
    contract_ref: Mapped[str] = mapped_column(String(60))
    country: Mapped[str] = mapped_column(String(60))

    requests: Mapped[list["PurchaseRequest"]] = relationship(back_populates="supplier")


class PurchaseRequest(Base):
    __tablename__ = "purchase_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"))
    department: Mapped[str] = mapped_column(String(80))
    items: Mapped[list] = mapped_column(JSON, default=list)
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(32), default="submitted")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Scenario tags used by the negative test cases (TEST-002..007).
    scenario_tag: Mapped[str | None] = mapped_column(String(48), nullable=True)

    employee: Mapped[Employee] = relationship(back_populates="requests")
    supplier: Mapped[Supplier | None] = relationship(back_populates="requests")
    events: Mapped[list["WorkflowEvent"]] = relationship(back_populates="request")


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    employee_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    application: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    request_id: Mapped[str | None] = mapped_column(ForeignKey("purchase_requests.id"), nullable=True, index=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    request: Mapped[PurchaseRequest | None] = relationship(back_populates="events")


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    rule: Mapped[str] = mapped_column(Text)
    effective_date: Mapped[datetime] = mapped_column(DateTime)
    department: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(20))

    incidents: Mapped[list["Incident"]] = relationship(back_populates="linked_policy")


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    date: Mapped[datetime] = mapped_column(DateTime)
    reason: Mapped[str] = mapped_column(Text)
    participants: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    outcome: Mapped[str] = mapped_column(String(120))

    incidents: Mapped[list["Incident"]] = relationship(back_populates="linked_decision")


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    date: Mapped[datetime] = mapped_column(DateTime)
    severity: Mapped[str] = mapped_column(String(20))
    impact: Mapped[str] = mapped_column(Text)
    linked_policy_id: Mapped[str | None] = mapped_column(ForeignKey("policies.id"), nullable=True)
    linked_decision_id: Mapped[str | None] = mapped_column(ForeignKey("decisions.id"), nullable=True)

    linked_policy: Mapped[Policy | None] = relationship(back_populates="incidents", foreign_keys=[linked_policy_id])
    linked_decision: Mapped[Decision | None] = relationship(back_populates="incidents", foreign_keys=[linked_decision_id])


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text, default="")
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    date_range: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    discovery_method: Mapped[str] = mapped_column(String(80), default="event-sequence-clustering")
    status: Mapped[str] = mapped_column(String(32), default="discovered")

    steps: Mapped[list["Step"]] = relationship(
        back_populates="workflow",
        order_by="Step.order_index",
        cascade="all, delete-orphan",
    )
    runs: Mapped[list["WorkflowRun"]] = relationship(back_populates="workflow")


class Step(Base):
    __tablename__ = "steps"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    order_index: Mapped[int] = mapped_column(Integer)
    actor_role: Mapped[str] = mapped_column(String(80))
    step_type: Mapped[str] = mapped_column("type", String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    automation_class: Mapped[str | None] = mapped_column(String(24), nullable=True)
    automation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_manual_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    depends_on: Mapped[list] = mapped_column(JSON, default=list)

    workflow: Mapped[Workflow] = relationship(back_populates="steps")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        # At most one live run per (workflow, request). Terminal runs that were
        # rejected or failed are excluded so a retry is still possible.
        Index(
            "uq_workflow_runs_live_request",
            "workflow_id",
            "request_id",
            unique=True,
            sqlite_where=text("state NOT IN ('rejected', 'failed')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), index=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("purchase_requests.id"), index=True)
    state: Mapped[str] = mapped_column(String(32), default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    purchase_order_id: Mapped[str | None] = mapped_column(String(48), nullable=True)

    workflow: Mapped[Workflow] = relationship(back_populates="runs")
    request: Mapped[PurchaseRequest] = relationship()
    run_steps: Mapped[list["RunStep"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunStep.id"
    )
    approvals: Mapped[list["Approval"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    snapshots: Mapped[list["MetricSnapshot"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class RunStep(Base):
    __tablename__ = "run_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    step_id: Mapped[str] = mapped_column(ForeignKey("steps.id"))
    state: Mapped[str] = mapped_column(String(32), default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(60), nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[WorkflowRun] = relationship(back_populates="run_steps")
    step: Mapped[Step] = relationship()


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    step_id: Mapped[str] = mapped_column(ForeignKey("steps.id"))
    required_role: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(24), default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[WorkflowRun] = relationship(back_populates="approvals")
    step: Mapped[Step] = relationship()


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    phase: Mapped[str] = mapped_column(String(40))
    metric_key: Mapped[str] = mapped_column(String(64))
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="none")
    measured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    run: Mapped[WorkflowRun] = relationship(back_populates="snapshots")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("purchase_requests.id"), index=True)
    run_id: Mapped[str] = mapped_column(String(48), index=True)
    # A run must never produce two purchase orders, even under concurrent retries.
    approval_id: Mapped[str] = mapped_column(String(48), unique=True)
    supplier_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(24), default="issued")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
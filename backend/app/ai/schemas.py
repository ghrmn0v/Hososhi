"""AI output schemas for the four roles.

These are the Developer 2 owned schemas (backend/app/ai/schemas.py per the
shared plan). Every model response is validated against one of these before it
can leave this layer.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AutomationClass(str, Enum):
    """Canonical wire values. UI displays 'SAFE / HUMAN REVIEW / HUMAN REQUIRED'."""

    SAFE = "SAFE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"


class Role(str, Enum):
    EXTRACT = "extract"
    UNDERSTAND = "understand"
    EXPLAIN = "explain"
    CLASSIFY = "classify"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# extract
# --------------------------------------------------------------------------- #


class ExtractionResult(StrictModel):
    request_id: str | None = None
    supplier: str | None = None
    items: list[str] = Field(default_factory=list)
    amount: float | None = None
    currency: str | None = None
    department: str | None = None
    requester: str | None = None
    insufficient_context: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    notes: str = ""


# --------------------------------------------------------------------------- #
# understand
# --------------------------------------------------------------------------- #


class StepUnderstanding(StrictModel):
    step_id: str | None = None
    step_name: str = ""
    purpose: str = ""
    actor_role: str = ""
    insufficient_context: bool = False
    evidence_refs: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# explain
# --------------------------------------------------------------------------- #


class StepExplanation(StrictModel):
    step_id: str | None = None
    question: str = "Why does this step exist?"
    summary: str = ""
    answer: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    insufficient_context: bool = False

    @field_validator("answer")
    @classmethod
    def answer_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("answer must not be blank")
        return value

    @property
    def has_conflicting_evidence(self) -> bool:
        return len(self.conflicts) > 1


# --------------------------------------------------------------------------- #
# classify
# --------------------------------------------------------------------------- #


class AutomationClassification(StrictModel):
    step_id: str | None = None
    automation_class: AutomationClass
    reason: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    insufficient_context: bool = False

    @field_validator("requires_approval")
    @classmethod
    def approval_flag_matches_class(cls, value: bool, info) -> bool:
        automation_class = info.data.get("automation_class")
        if isinstance(automation_class, AutomationClass):
            if automation_class is AutomationClass.HUMAN_REQUIRED and not value:
                raise ValueError("HUMAN_REQUIRED implies requires_approval=true")
        return value


# --------------------------------------------------------------------------- #
# evidence / API shapes
# --------------------------------------------------------------------------- #

EvidenceType = Literal["policy", "decision", "incident", "event"]


class EvidenceItem(StrictModel):
    ref: str
    type: EvidenceType
    title: str
    snippet: str
    relevance: float = Field(ge=0.0, le=1.0)
    date: str | None = None


class StepIntelligenceResponse(StrictModel):
    """Contract for endpoint 6, as frozen in the v1 API contract."""

    step_id: str
    question: str = "Why does this step exist?"
    summary: str
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceItem]
    model: str
    generated_at: str
    fallback_used: bool = False
    insufficient_context: bool = False
    assumptions: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class EvidenceListResponse(StrictModel):
    """Contract for endpoint 7."""

    workflow_id: str | None = None
    step_id: str | None = None
    evidence: list[EvidenceItem]
    returned: int
    retrieval: dict[str, object] = Field(default_factory=dict)


class AutomationStepResult(StrictModel):
    step_id: str
    name: str = ""
    automation_class: AutomationClass
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    requires_approval: bool
    safety_override: bool = False
    override_reason: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    model: str = ""


class AutomationSummary(StrictModel):
    safe: int = 0
    human_review: int = 0
    human_required: int = 0


class AutomationAnalyzeResponse(StrictModel):
    """Contract for endpoint 8."""

    workflow_id: str
    policy_rules_version: str = "safety-rules-v1"
    summary: AutomationSummary
    steps: list[AutomationStepResult]
    model: str = ""
    generated_at: str = ""
    fallback_used: bool = False


ROLE_SCHEMAS: dict[Role, type[StrictModel]] = {
    Role.EXTRACT: ExtractionResult,
    Role.UNDERSTAND: StepUnderstanding,
    Role.EXPLAIN: StepExplanation,
    Role.CLASSIFY: AutomationClassification,
}
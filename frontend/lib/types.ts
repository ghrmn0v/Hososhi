/**
 * Response shapes consumed by the frontend.
 * These mirror backend/app/schemas.py (the frozen API contract).
 *
 * Rules that apply to everything in this file:
 *  - A metric may be `null`. `null` means "not measured" and must render as text,
 *    never as 0 and never as a fabricated number.
 *  - Automation class is one of three values and is always shown with a text label.
 */

export type AutomationClass = 'SAFE' | 'HUMAN_REVIEW' | 'HUMAN_REQUIRED';

export type EvidenceType = 'policy' | 'decision' | 'incident' | 'event';

export interface ErrorBody {
  code: string;
  message: string;
  retryable: boolean;
  request_id: string | null;
}

/* ---------- 2. GET /dashboard ---------- */

export interface DashboardWorkflow {
  workflow_id: string;
  name: string;
  category: string | null;
  executions: number | null;
  avg_duration_ms: number | null;
  last_activity_at: string | null;
}

export interface DashboardActivity {
  at: string | null;
  label: string;
  workflow_name: string | null;
}

export interface Dashboard {
  workflows_discovered: number | null;
  automation_opportunities: number | null;
  workflow_executions: number | null;
  time_saved_ms: number | null;
  /** Set when time_saved_ms is an estimate rather than a measurement. */
  time_saved_is_estimate: boolean;
  workflows: DashboardWorkflow[];
  recent_activity: DashboardActivity[];
}

/* ---------- 3/4. GET /workflows, GET /workflows/{id} ---------- */

export interface Step {
  step_id: string;
  name: string;
  order: number;
  description: string | null;
  automation_class: AutomationClass | null;
}

export interface WorkflowDetail {
  workflow_id: string;
  name: string;
  category: string | null;
  description: string | null;
  discovered_at: string | null;
  event_count: number | null;
  executions: number | null;
  avg_duration_ms: number | null;
  last_activity_at: string | null;
  automation_potential: number | null;
  steps: Step[];
}

/* ---------- 6. GET /steps/{sid}/intelligence ---------- */

export interface Evidence {
  ref: string;
  type: EvidenceType;
  title: string;
  snippet: string | null;
  relevance: number | null;
  date: string | null;
}

export interface Intelligence {
  step_id: string;
  question: string;
  summary: string | null;
  answer: string | null;
  confidence: number | null;
  evidence: Evidence[];
  model: string | null;
  generated_at: string | null;
  fallback_used: boolean;
}

/* ---------- 7. GET /workflows/{wid}/evidence ---------- */

export type EvidenceList = Evidence[];

/* ---------- 8. POST /automation/analyze ---------- */

export interface AnalyzedStep {
  step_id: string;
  name: string;
  automation_class: AutomationClass;
  reason: string | null;
  confidence: number | null;
  requires_approval: boolean;
}

export interface Analysis {
  workflow_id: string;
  policy_rules_version: string;
  summary: {
    safe: number;
    human_review: number;
    human_required: number;
  };
  steps: AnalyzedStep[];
}

/* ---------- 9/10. POST /automation/run, GET /runs/{run_id} ---------- */

export type RunStepState =
  | 'pending'
  | 'running'
  | 'completed'
  | 'waiting_approval'
  | 'rejected'
  | 'failed';

export type RunState =
  | 'pending'
  | 'running'
  | 'waiting_approval'
  | 'completed'
  | 'rejected'
  | 'failed';

export interface RunStep {
  step_id: string;
  name: string;
  automation_class: AutomationClass;
  state: RunStepState;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  actor: string | null;
  output_summary: string | null;
  approval_id: string | null;
}

export interface Run {
  run_id: string;
  workflow_id: string;
  state: RunState;
  started_at: string | null;
  finished_at: string | null;
  steps: RunStep[];
  blocked_on: string | null;
  /** Purchase order, present only when the run completed after an approval. */
  purchase_order: PurchaseOrder | null;
}

/* ---------- 11. POST /approvals/{id} ---------- */

export interface ApprovalDecision {
  decision: 'approve' | 'reject';
  approver_id: string;
  comment: string;
}

export interface ApprovalResult {
  approval_id: string;
  run_id: string;
  state: 'approved' | 'rejected';
  decided_by: string | null;
  decided_at: string | null;
}

/* ---------- 12. GET /results/{run_id} ---------- */

export type SourceKind =
  | 'replayed_from_dataset'
  | 'measured_in_this_run'
  | 'none';

export interface MetricsBlock {
  label: string;
  source: SourceKind;
  total_duration_ms: number | null;
  manual_steps: number | null;
  human_decisions: number | null;
  automation_rate: number | null;
  errors: number | null;
}

export interface Results {
  run_id: string;
  workflow_id: string;
  measured_at: string | null;
  measurement_method: string | null;
  runs_count: number | null;
  baseline: MetricsBlock;
  ai_assisted: MetricsBlock;
  delta: {
    duration_ms: number | null;
    duration_percent: number | null;
    human_interventions: number | null;
  };
  is_measured: boolean;
}

/* ---------- 13. GET /meta ---------- */

export interface Meta {
  dataset: {
    synthetic: boolean;
    description: string | null;
    events: number | null;
    seeded_at: string | null;
  };
  ai: {
    provider: string | null;
    model: string | null;
    fallback_used: boolean;
  };
}

/* ---------- derived shapes ---------- */

export interface PurchaseOrder {
  order_id: string;
  request_id: string;
  supplier: string | null;
  amount: number | null;
  currency: string | null;
  created_at: string | null;
  created_by: string | null;
}
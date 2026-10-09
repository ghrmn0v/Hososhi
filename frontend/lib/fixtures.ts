/**
 * Fixture mode — DEVELOPMENT ONLY.
 *
 * Enabled with NEXT_PUBLIC_USE_FIXTURES=true. It routes the API client to static JSON
 * files in `public/fixtures/` plus a small in-memory simulation of the run lifecycle,
 * so the UI can be built before the backend exists.
 *
 * Honesty rules that apply to this file:
 *  - No fixture value is presented as a measurement. Step timings in the simulated run
 *    are synthetic and labelled as such, and the results fixture returns null metrics
 *    with source "none", so the Results screen renders "not measured" instead of a
 *    number that looks real.
 *  - If fixtures are ever left enabled at demo time this must be disclosed. The app
 *    footer says so on screen.
 */

import { ApiError } from './errors';
import type {
  Analysis,
  ApprovalDecision,
  ApprovalResult,
  Dashboard,
  EvidenceList,
  Intelligence,
  Meta,
  PurchaseOrder,
  Results,
  Run,
  WorkflowDetail,
} from './types';

const cache = new Map<string, unknown>();

async function load<T>(file: string): Promise<T> {
  const hit = cache.get(file);
  if (hit) return structuredClone(hit) as T;

  // no-cache so an edited fixture shows up on reload during development
const res = await fetch(`/fixtures/${file}`, { cache: 'no-cache' });
  if (!res.ok) {
    throw new ApiError(`Fixture ${file} could not be loaded.`, {
      code: 'INTERNAL_ERROR',
      retryable: false,
      requestId: null,
      status: 0,
    });
  }
  const data = (await res.json()) as unknown;
  cache.set(file, data);
  return structuredClone(data) as T;
}

/* ---------- simulated run lifecycle ---------- */

const RUN_ID = 'run_fixture';
const APPROVAL_ID = 'apr_fixture';
const RUN_START = Date.now();

/** Synthetic step durations. These are simulated, not measured. */
const SIMULATED_STEP_MS: Record<string, number> = {
  stp_extract: 410,
  stp_supplier: 260,
  stp_price: 380,
  stp_policy: 300,
};

interface RunState {
  run: Run;
  approval: ApprovalResult | null;
}

let runState: RunState | null = null;

function at(offsetMs: number): string {
  return new Date(RUN_START + offsetMs).toISOString();
}

function now(): string {
  return new Date().toISOString();
}

function buildRun(): Run {
  let t = 0;
  const step = (
    step_id: string,
    name: string,
    automation_class: Run['steps'][number]['automation_class'],
    durationMs: number,
    output_summary: string,
  ): Run['steps'][number] => {
    const started_at = at(t);
    t += durationMs;
    return {
      step_id,
      name,
      automation_class,
      state: 'completed',
      started_at,
      finished_at: at(t),
      duration_ms: durationMs,
      actor: 'system',
      output_summary,
      approval_id: null,
    };
  };

  return {
    run_id: RUN_ID,
    workflow_id: 'wf_purchase_request',
    state: 'waiting_approval',
    started_at: at(0),
    finished_at: null,
    steps: [
      step(
        'stp_extract',
        'Extract request information',
        'SAFE',
        SIMULATED_STEP_MS.stp_extract,
        'Simulated: fields read from the request document.',
      ),
      step(
        'stp_supplier',
        'Identify supplier',
        'SAFE',
        SIMULATED_STEP_MS.stp_supplier,
        'Simulated: matched against the supplier register.',
      ),
      step(
        'stp_price',
        'Verify price',
        'SAFE',
        SIMULATED_STEP_MS.stp_price,
        'Simulated: quoted price compared with the recorded supplier price.',
      ),
      step(
        'stp_policy',
        'Check company policy',
        'SAFE',
        SIMULATED_STEP_MS.stp_policy,
        'Simulated: written policy rules applied.',
      ),
      {
        step_id: 'stp_history',
        name: 'Search historical decisions',
        automation_class: 'HUMAN_REVIEW',
        state: 'completed',
        started_at: null,
        finished_at: null,
        duration_ms: null,
        actor: 'system',
        output_summary: 'Simulated: past decisions retrieved for a person to review.',
        approval_id: null,
      },
      {
        step_id: 'stp_approval',
        name: 'Manager approval',
        automation_class: 'HUMAN_REQUIRED',
        state: 'waiting_approval',
        started_at: null,
        finished_at: null,
        duration_ms: null,
        actor: null,
        output_summary: null,
        approval_id: APPROVAL_ID,
      },
      {
        step_id: 'stp_po',
        name: 'Create purchase order',
        automation_class: 'SAFE',
        state: 'pending',
        started_at: null,
        finished_at: null,
        duration_ms: null,
        actor: null,
        output_summary: null,
        approval_id: null,
      },
    ],
    blocked_on: `approval:${APPROVAL_ID}`,
    purchase_order: null,
  };
}

/* ---------- path routing ---------- */

export async function getFixture(
  rawPath: string,
  method: string,
  body?: unknown,
): Promise<unknown> {
  const path = rawPath.split('?')[0];
  const key = `${method} ${path}`;
  const notFound: () => never = () => {
    throw new ApiError(`No fixture registered for ${key}.`, {
      code: 'NOT_FOUND',
      retryable: false,
      requestId: null,
      status: 404,
    });
  };

  if (key === 'GET /api/v1/health') return { status: 'ok (fixtures)' };
  if (key === 'GET /api/v1/dashboard') return load<Dashboard>('dashboard.json');
  if (key === 'GET /api/v1/meta') return load<Meta>('meta.json');

  const workflowMatch = /^\/api\/v1\/workflows\/([^/]+)$/.exec(path);
  if (method === 'GET' && workflowMatch) {
    return load<WorkflowDetail>(`workflow-${workflowMatch[1]}.json`);
  }

  const intelligenceMatch =
    /^\/api\/v1\/workflows\/[^/]+\/steps\/([^/]+)\/intelligence$/.exec(path);
  if (method === 'GET' && intelligenceMatch) {
    const all = await load<Record<string, Intelligence>>('intelligence.json');
    // A step with no recorded explanation returns a real empty answer rather than an
    // invented one, so the empty state is exercised honestly.
    return (
      all[intelligenceMatch[1]] ?? {
        step_id: intelligenceMatch[1],
        question: 'Why does this step exist?',
        summary: null,
        answer: null,
        confidence: null,
        evidence: [],
        model: null,
        generated_at: null,
        fallback_used: false,
      }
    );
  }

  const stepMatch = /^\/api\/v1\/workflows\/([^/]+)\/steps\/([^/]+)$/.exec(path);
  if (method === 'GET' && stepMatch) {
    const wf = await load<WorkflowDetail>(`workflow-${stepMatch[1]}.json`);
    const found = wf.steps.find((s) => s.step_id === stepMatch[2]);
    if (!found) notFound();
    return found;
  }

  if (method === 'GET' && path.includes('/evidence')) {
    const wfId = path.split('/')[4];
    const byWorkflow = await load<Record<string, EvidenceList>>('evidence.json');
    return byWorkflow[wfId] ?? [];
  }

  const analyzeMatch = /^\/api\/v1\/workflows\/([^/]+)\/automation\/analyze$/.exec(path);
  if (method === 'POST' && analyzeMatch) {
    return load<Analysis>('analysis.json');
  }

  const startMatch = /^\/api\/v1\/workflows\/([^/]+)\/automation\/run$/.exec(path);
  if (method === 'POST' && startMatch) {
    runState = { run: buildRun(), approval: null };
    return runState.run;
  }

  const runMatch = /^\/api\/v1\/runs\/([^/]+)$/.exec(path);
  if (method === 'GET' && runMatch) {
    const state = runState;
    if (!state) notFound();
    return state.run;
  }

  const approvalMatch = /^\/api\/v1\/approvals\/([^/]+)$/.exec(path);
  if (method === 'POST' && approvalMatch) {
    const state = runState;
    if (!state) notFound();

    // Mirrors the backend rule: only POST /approvals advances a HUMAN REQUIRED step.
    if (state.run.state !== 'waiting_approval') {
      throw new ApiError('This approval was already decided.', {
        code: 'INVALID_STATE_TRANSITION',
        retryable: false,
        requestId: 'req_fixture',
        status: 409,
      });
    }

    const decision = (body ?? {}) as ApprovalDecision;
    const approved = decision.decision === 'approve';
    const at_time = now();

    state.approval = {
      approval_id: APPROVAL_ID,
      run_id: RUN_ID,
      state: approved ? 'approved' : 'rejected',
      decided_by: decision.approver_id ?? null,
      decided_at: at_time,
    };

    const approvalStep = state.run.steps.find((s) => s.step_id === 'stp_approval');
    if (approvalStep) {
      approvalStep.state = approved ? 'completed' : 'rejected';
      approvalStep.actor = decision.approver_id ?? null;
      approvalStep.finished_at = at_time;
    }

    if (approved) {
      const poStep = state.run.steps.find((s) => s.step_id === 'stp_po');
      if (poStep) {
        poStep.state = 'completed';
        poStep.actor = 'system';
        poStep.started_at = at_time;
        poStep.finished_at = at_time;
        poStep.output_summary = 'Simulated: purchase order created after approval.';
      }
      const po: PurchaseOrder = {
        order_id: 'po_fixture',
        request_id: 'pr_fixture',
        supplier: null,
        amount: null,
        currency: null,
        created_at: at_time,
        created_by: 'system',
      };
      state.run.purchase_order = po;
    }

    state.run.state = approved ? 'completed' : 'rejected';
    state.run.finished_at = at_time;
    state.run.blocked_on = null;

    return state.approval;
  }

  const resultsMatch = /^\/api\/v1\/results\/([^/]+)$/.exec(path);
  if (method === 'GET' && resultsMatch) {
    const state = runState;
    if (!state) notFound();
    // Nothing was measured: every metric is null, so the UI must say "not measured".
    const block = (label: string) => ({
      label,
      source: 'none' as const,
      total_duration_ms: null,
      manual_steps: null,
      human_decisions: null,
      automation_rate: null,
      errors: null,
    });
    return {
      run_id: RUN_ID,
      workflow_id: 'wf_purchase_request',
      measured_at: null,
      measurement_method:
        'Fixture mode — no measurement was taken. Timings in the run view are simulated.',
      runs_count: null,
      baseline: block('Human-only'),
      ai_assisted: block('AI-assisted'),
      delta: { duration_ms: null, duration_percent: null, human_interventions: null },
      is_measured: false,
    } satisfies Results;
  }

  return notFound();
}
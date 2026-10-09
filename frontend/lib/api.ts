/**
 * Typed API client.
 *
 * Every call goes through here so the base URL, typed errors and the fixture switch
 * live in exactly one place.
 *
 * Base URL comes from NEXT_PUBLIC_API_BASE_URL. It is never hardcoded.
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
  Results,
  Run,
  Step,
  WorkflowDetail,
} from './types';

export { ApiError };

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? '';
const FIXTURE_MODE = process.env.NEXT_PUBLIC_USE_FIXTURES === 'true';

type FetchOptions = {
  method?: 'GET' | 'POST';
  body?: unknown;
  signal?: AbortSignal;
};

async function call<T>(path: string, opts: FetchOptions = {}): Promise<T> {
  const method = opts.method ?? 'GET';

  if (FIXTURE_MODE) {
    const { getFixture } = await import('./fixtures');
    // A short delay keeps the loading states honest while developing.
    await new Promise((r) => setTimeout(r, 120));
    return (await getFixture(path, method, opts.body)) as T;
  }

  if (!BASE_URL) {
    throw new ApiError('NEXT_PUBLIC_API_BASE_URL is not set.', {
      code: 'INTERNAL_ERROR',
      retryable: false,
      requestId: null,
      status: 0,
    });
  }

  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: opts.body ? { 'content-type': 'application/json' } : undefined,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
      cache: 'no-store',
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw new ApiError('The backend could not be reached.', {
      code: 'NETWORK_UNREACHABLE',
      retryable: true,
      requestId: null,
      status: 0,
    });
  }

  if (!res.ok) {
    let parsed: { error?: Record<string, unknown> } | null = null;
    try {
      parsed = (await res.json()) as { error?: Record<string, unknown> };
    } catch {
      // non-JSON error body; the defaults below apply
    }
    const e = parsed?.error ?? {};
    throw new ApiError(
      typeof e.message === 'string' && e.message
        ? e.message
        : `The request failed with status ${res.status}.`,
      {
        code: typeof e.code === 'string' ? e.code : 'INTERNAL_ERROR',
        retryable: e.retryable === true,
        requestId: typeof e.request_id === 'string' ? e.request_id : null,
        status: res.status,
      },
    );
  }

  return (await res.json()) as T;
}

export const api = {
  isFixtureMode: FIXTURE_MODE,

  health: () => call<{ status: string }>('/api/v1/health'),

  dashboard: (signal?: AbortSignal) => call<Dashboard>('/api/v1/dashboard', { signal }),

  workflow: (workflowId: string, signal?: AbortSignal) =>
    call<WorkflowDetail>(`/api/v1/workflows/${workflowId}`, { signal }),

  step: (workflowId: string, stepId: string, signal?: AbortSignal) =>
    call<Step>(`/api/v1/workflows/${workflowId}/steps/${stepId}`, { signal }),

  intelligence: (workflowId: string, stepId: string, signal?: AbortSignal) =>
    call<Intelligence>(`/api/v1/workflows/${workflowId}/steps/${stepId}/intelligence`, {
      signal,
    }).then((data) => {
      // Normalize timestamp: backend returns 'measured_at', frontend expects 'generated_at'
      if (data.measured_at !== undefined) {
        data.generated_at = data.measured_at;
        delete data.measured_at;
      }
      return data;
    }),

  evidence: (
    workflowId: string,
    params?: { step_id?: string; type?: string },
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams();
    if (params?.step_id) q.set('step_id', params.step_id);
    if (params?.type) q.set('type', params.type);
    const qs = q.toString();
    return call<EvidenceList>(
      `/api/v1/workflows/${workflowId}/evidence${qs ? `?${qs}` : ''}`,
      {
        signal,
    }).then((result) => {
      // Normalize evidence item IDs: backend uses 'id', frontend expects 'ref'
      if (result.evidence) {
        result.evidence = result.evidence.map((ev) => ({
          ...ev,
          ref: ev.id,
        }));
      }
      return result;
    }),
  },

  startRun: (workflowId: string, signal?: AbortSignal) =>
    call<Run>(`/api/v1/workflows/${workflowId}/automation/run`, {
      method: 'POST',
      body: {},
      signal,
    }),

  run: (runId: string, signal?: AbortSignal) => call<Run>(`/api/v1/runs/${runId}`, { signal }),

  decide: (approvalId: string, decision: ApprovalDecision) =>
    call<ApprovalResult>(`/api/v1/approvals/${approvalId}`, {
      method: 'POST',
      body: decision,
    }),

  results: (runId: string, signal?: AbortSignal) =>
    call<Results>(`/api/v1/results/${runId}`, { signal }),

  meta: (signal?: AbortSignal) => call<Meta>('/api/v1/meta', { signal }),
};

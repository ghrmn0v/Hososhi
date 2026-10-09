'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { clockTime } from '@/lib/format';
import { ClassBadge } from '@/components/ClassBadge';
import { EmptyCard, ErrorCard, LoadingCard } from '@/components/States';
import { Breadcrumb } from '@/components/Chrome';
import type { Run, RunStep, RunStepState } from '@/lib/types';

const POLL_MS = 1500;

/**
 * Screen 5 — Automation Run.
 *
 * Polls GET /runs/{run_id} every ~1.5s (polling only; no websocket layer). Stops at the
 * HUMAN REQUIRED step and hands control to the Human Approval screen. A rejected run and
 * a completed run look clearly different.
 */
export function AutomationRun({
  workflowId,
  runId,
}: {
  workflowId: string;
  runId?: string;
}) {
  const router = useRouter();

  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    let alive = true;

    function isAbort(err: unknown): boolean {
      return err instanceof DOMException && err.name === 'AbortError';
    }

    async function pollLoop(id: string) {
      try {
        const next = await api.run(id, ac.signal);
        if (!alive) return;
        setRun(next);
        setError(null);

        // Keep polling only while the run can still change.
        if (next.state === 'waiting_approval' || next.state === 'running') {
          timer.current = setTimeout(() => {
            void pollLoop(id);
          }, POLL_MS);
        } else {
          setLoading(false);
        }
      } catch (err) {
        if (!alive || isAbort(err)) return;
        setError(err);
        setLoading(false);
      }
    }

    async function boot() {
      try {
        let id = runId;
        if (!id) {
          // No run id in the URL yet — start one so the screen is never blank.
          const started = await api.startRun(workflowId, ac.signal);
          if (!alive) return;
          id = started.run_id;
          setRun(started);
          router.replace(`/workflows/${workflowId}/automation/run/${id}`);
        }
        await pollLoop(id);
      } catch (err) {
        if (!alive || isAbort(err)) return;
        setError(err);
        setLoading(false);
      }
    }

    void boot();

    return () => {
      alive = false;
      ac.abort();
      if (timer.current) clearTimeout(timer.current);
    };
  }, [workflowId, runId, router, retry]);

  return (
    <>
      <Breadcrumb
        items={[
          { label: 'Automation', href: `/workflows/${workflowId}/automation` },
          { label: 'Workflow', href: `/workflows/${workflowId}` },
          { label: 'Run' },
        ]}
      />

      <div className="page">
        <h1 style={{ fontSize: 26, margin: '8px 0 24px' }}>
          {loading && !run ? 'Automation run' : titleFor(run)}
        </h1>

        {loading && !run ? <LoadingCard label="LOADING · RUN" lines={4} /> : null}

        {error ? (
          <ErrorCard
            error={error}
            onRetry={() => {
              setError(null);
              setLoading(true);
              setRetry((n) => n + 1);
            }}
            title="Automation stopped because a step failed."
          />
        ) : null}

        {run ? <RunBody run={run} workflowId={workflowId} /> : null}
      </div>
    </>
  );
}

function titleFor(run: Run | null): string {
  switch (run?.state) {
    case 'waiting_approval':
      return 'Waiting for your approval';
    case 'completed':
      return 'Run completed';
    case 'rejected':
      return 'Run stopped — rejected';
    case 'failed':
      return 'Run failed';
    default:
      return 'Automation run';
  }
}

function RunBody({ run, workflowId }: { run: Run; workflowId: string }) {
  const approvalStep = run.steps.find((s) => s.approval_id);
  const rejected = run.state === 'rejected';
  const completed = run.state === 'completed';

  return (
    <div className="row" style={{ alignItems: 'flex-start' }}>
      <div className="card t" style={{ width: 380, flex: '0 0 380px' }}>
        <div className="lab" style={{ marginBottom: 8 }}>
          PROGRESS
        </div>

        {run.steps.length === 0 ? (
          <EmptyCard
            title="This run has no steps"
            detail="The backend returned no steps for this run."
          />
        ) : (
          run.steps.map((s) => <ProgressRow key={s.step_id} step={s} />)
        )}
      </div>

      <div style={{ flex: '1 1 0%' }} className="stack">
        {rejected ? (
          <div className="card t alert">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 style={{ fontSize: 20 }}>Rejected by a person</h2>
              <span className="bd q">REJECTED</span>
            </div>
            <p style={{ margin: '10px 0 18px', fontSize: 14, lineHeight: 1.6 }}>
              A manager rejected this run. No purchase order was created and nothing was
              committed. This outcome is recorded in the run history.
            </p>
            <div className="row" style={{ gap: 8 }}>
              <Link className="btn" href={`/workflows/${workflowId}`}>
                Back to workflow
              </Link>
              <Link className="btn o" href={`/workflows/${workflowId}/automation`}>
                Start a new run
              </Link>
            </div>
          </div>
        ) : null}

        {completed ? (
          <div className="card t">
            <div style={{ display: 'flex', alignItems: 'center', gap: 24, marginBottom: 20 }}>
              <span className="stamp done">COMPLETED</span>
              <div>
                <h2 style={{ fontSize: 20 }}>Purchase order created</h2>
                <p className="m" style={{ marginTop: 6 }}>
                  Finished at {clockTime(run.finished_at)}
                </p>
              </div>
            </div>

            <PoSummary run={run} />

            <div className="row" style={{ gap: 8, marginTop: 20 }}>
              <Link className="btn o" href={`/workflows/${workflowId}`}>
                Back to workflow
              </Link>
              <Link className="btn" href={`/workflows/${workflowId}/automation/run/${run.run_id}/results`}>
                View results
              </Link>
            </div>
          </div>
        ) : null}

        {run.state === 'waiting_approval' && approvalStep ? (
          <div className="card t alert">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 style={{ fontSize: 20 }}>Waiting for approval</h2>
              <ClassBadge value={approvalStep.automation_class} />
            </div>
            <p style={{ margin: '10px 0 18px', fontSize: 14, lineHeight: 1.6 }}>
              The run is paused at <b>{approvalStep.name}</b>. Nothing else happens until a
              manager decides. {approvalStep.started_at ? `Requested at ${clockTime(approvalStep.started_at)}.` : ''}
            </p>
            <div className="m" style={{ marginBottom: 18 }}>
              Next after approval:{' '}
              {run.steps.find((s) => s.step_id === 'stp_po')?.name ?? 'the next step'}
            </div>
            <Link className="btn" href={`/workflows/${workflowId}/automation/run/${run.run_id}/approval`}>
              Review and decide
            </Link>
          </div>
        ) : null}

        {run.state === 'running' || run.state === 'pending' ? (
          <div className="card t">
            <h2 style={{ fontSize: 18 }}>Run in progress</h2>
            <p className="m" style={{ marginTop: 10 }}>
              The backend is advancing the steps it is allowed to run. This screen updates
              automatically.
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function PoSummary({ run }: { run: Run }) {
  const po = run.purchase_order;
  if (!po) {
    return (
      <p className="m">
        The run completed but the API returned no purchase order for it.
      </p>
    );
  }
  return (
    <div className="row" style={{ gap: 16, flexWrap: 'wrap' }}>
      <Field label="ORDER" value={po.order_id} />
      <Field label="REQUEST" value={po.request_id} />
      <Field label="SUPPLIER" value={po.supplier ?? 'not reported'} />
      <Field label="CREATED AT" value={clockTime(po.created_at)} />
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ minWidth: 160 }}>
      <div className="lab">{label}</div>
      <div style={{ marginTop: 4, fontSize: 14 }}>{value}</div>
    </div>
  );
}

function ProgressRow({ step }: { step: RunStep }) {
  const { glyph, tone } = visualFor(step.state);

  return (
    <div className="step-line" style={{ alignItems: 'center' }}>
      <span className={`num ${tone} r4`}>{glyph}</span>
      <span className="grow">
        {step.name}
        {step.output_summary ? (
          <div className="m" style={{ marginTop: 4, fontSize: 12 }}>
            {step.output_summary}
          </div>
        ) : null}
      </span>
      <span className="m" style={{ whiteSpace: 'nowrap' }}>
        {step.state === 'waiting_approval'
          ? 'now'
          : step.finished_at
            ? clockTime(step.finished_at)
            : step.state === 'pending'
              ? 'after approval'
              : '--:--'}
      </span>
    </div>
  );
}

/** Completed ✓, waiting ⏸ (II), pending ○, rejected ✗, failed !. */
function visualFor(state: RunStepState): { glyph: string; tone: string } {
  switch (state) {
    case 'completed':
      return { glyph: '✓', tone: 'done' };
    case 'running':
      return { glyph: '…', tone: '' };
    case 'waiting_approval':
      return { glyph: 'II', tone: 'wait' };
    case 'rejected':
      return { glyph: '✗', tone: 'wait' };
    case 'failed':
      return { glyph: '!', tone: 'wait' };
    case 'pending':
    default:
      return { glyph: '○', tone: 'pending' };
  }
}
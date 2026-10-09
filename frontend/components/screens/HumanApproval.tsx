'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { api } from '@/lib/api';
import { ApiError } from '@/lib/errors';
import { confidence, dateOnly } from '@/lib/format';
import { ClassBadge } from '@/components/ClassBadge';
import { EmptyCard, ErrorCard, LoadingCard } from '@/components/States';
import { Breadcrumb } from '@/components/Chrome';
import { useResource } from '@/lib/useResource';
import type { Run } from '@/lib/types';

/**
 * Human Approval — the most important moment in the product, so it carries the strongest
 * visual weight. Both buttons are disabled while the request is in flight.
 *
 * The frontend does not enforce anything here: it reflects the backend's decision state.
 * A 409 INVALID_STATE_TRANSITION means someone already decided, and is shown as such.
 */
export function HumanApproval({
  workflowId,
  runId,
}: {
  workflowId: string;
  runId: string;
}) {
  const router = useRouter();

  const runRes = useResource((signal) => api.run(runId, signal), [runId]);
  const [comment, setComment] = useState('');
  const [inFlight, setInFlight] = useState<'approve' | 'reject' | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);

  async function decide(approvalId: string, decision: 'approve' | 'reject') {
    setInFlight(decision);
    setConflict(null);
    try {
      await api.decide(approvalId, {
        decision,
        approver_id: 'emp_current_user',
        comment,
      });
      router.push(`/workflows/${workflowId}/automation/run/${runId}`);
    } catch (err) {
      setInFlight(null);
      if (err instanceof ApiError && err.status === 409) {
        setConflict('This approval was already decided. Showing the current state.');
      }
    }
  }

  if (runRes.status === 'loading') {
    return (
      <>
        <ApprovalBreadcrumb workflowId={workflowId} label="Approval" />
        <div className="page">
          <LoadingCard label="LOADING · APPROVAL" lines={3} />
        </div>
      </>
    );
  }

  if (runRes.status === 'error') {
    return (
      <>
        <ApprovalBreadcrumb workflowId={workflowId} label="Approval" />
        <div className="page">
          <ErrorCard
            error={runRes.error}
            onRetry={runRes.reload}
            title="This approval could not be loaded."
          />
        </div>
      </>
    );
  }

  const run = runRes.data;
  const approvalStep = run.steps.find((s) => s.approval_id);

  if (!approvalStep) {
    return (
      <>
        <ApprovalBreadcrumb workflowId={workflowId} label="Approval" />
        <div className="page">
          <EmptyCard
            title="There is no approval waiting"
            detail="This run is not paused at a step that requires a human decision."
          />
        </div>
      </>
    );
  }

  return (
    <>
      <ApprovalBreadcrumb workflowId={workflowId} label="Approval" />

      <div className="page">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h1 style={{ fontSize: 26 }}>{approvalStep.name}</h1>
            <p className="m" style={{ margin: '6px 0 20px' }}>
              Run {run.run_id}
            </p>
          </div>
          <ClassBadge value={approvalStep.automation_class} />
        </div>

        <div
          className="card"
          style={{ marginBottom: 20, border: '2px solid var(--required-fg)', padding: '14px 20px', fontSize: 14 }}
        >
          <b>Execution is paused.</b> Human approval is required before the purchase order is
          created.
        </div>

        {conflict ? (
          <div style={{ marginBottom: 20 }}>
            <ErrorCard error={new ApiError(conflict, { code: 'INVALID_STATE_TRANSITION', retryable: false, requestId: null, status: 409 })} title="Already decided" onRetry={runRes.reload} />
          </div>
        ) : null}

        <div className="row" style={{ alignItems: 'flex-start' }}>
          <div style={{ flex: '1 1 0%' }} className="stack">
            <WhatWasChecked run={run} approvalStepName={approvalStep.name} />
            <AiRecommendation workflowId={workflowId} stepId={approvalStep.step_id} />
          </div>

          <div style={{ width: 340, flex: '0 0 340px' }}>
            <ApprovalPanel
              comment={comment}
              onComment={setComment}
              inFlight={inFlight}
              onDecide={(d) => decide(approvalStep.approval_id as string, d)}
              approvalId={approvalStep.approval_id as string}
              nextStepName={
                run.steps.find((s) => s.step_id === 'stp_po')?.name ?? 'the next step'
              }
            />
          </div>
        </div>
      </div>
    </>
  );
}

function ApprovalBreadcrumb({ workflowId, label }: { workflowId: string; label: string }) {
  return (
    <Breadcrumb
      items={[
        { label: 'Automation', href: `/workflows/${workflowId}/automation` },
        { label: 'Workflow', href: `/workflows/${workflowId}` },
        { label: 'Run' },
        { label },
      ]}
    />
  );
}

function WhatWasChecked({ run, approvalStepName }: { run: Run; approvalStepName: string }) {
  const checked = run.steps.filter((s) => s.state === 'completed' && s.step_id !== 'stp_po');

  return (
    <div className="card t">
      <h3 style={{ fontSize: 16, marginBottom: 6 }}>What the system already checked</h3>
      {checked.length === 0 ? (
        <p className="m" style={{ marginTop: 10 }}>
          No step was completed before this approval was requested.
        </p>
      ) : (
        checked.map((s, i) => (
          <div
            key={s.step_id}
            className={`step-line${i === 0 ? ' first' : ''}`}
            style={{ alignItems: 'center' }}
          >
            <span className="num done r4">✓</span>
            <span className="grow">{s.name}</span>
            <span className="m">
              {s.actor === 'system' ? 'Automated' : s.actor ? `By ${s.actor}` : 'Done'}
            </span>
          </div>
        ))
      )}
      <p className="m" style={{ marginTop: 12 }}>
        Next: {approvalStepName} requires your decision.
      </p>
    </div>
  );
}

function AiRecommendation({ workflowId, stepId }: { workflowId: string; stepId: string }) {
  const intel = useResource(
    (signal) => api.intelligence(workflowId, stepId, signal),
    [workflowId, stepId],
  );

  return (
    <div className="card t">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ fontSize: 16 }}>AI recommendation</h3>
        {intel.status === 'success' ? (
          <span className="m">Confidence {confidence(intel.data.confidence)}</span>
        ) : null}
      </div>

      {intel.status === 'loading' ? (
        <div style={{ marginTop: 12 }}>
          <div className="sk" style={{ width: '90%' }} />
          <div className="sk" style={{ width: '70%' }} />
        </div>
      ) : null}

      {intel.status === 'error' ? (
        <p className="m" style={{ marginTop: 10 }}>
          No recommendation is available. The decision does not depend on it.
        </p>
      ) : null}

      {intel.status === 'success' ? (
        <>
          <p style={{ margin: '10px 0 6px', fontSize: 14, lineHeight: 1.6 }}>
            {intel.data.summary ?? 'The system prepared the following for your review.'} The AI
            recommends; you decide.
          </p>
          {intel.data.evidence.slice(0, 2).map((ev) => (
            <div
              key={ev.ref}
              className="ln"
              style={{ alignItems: 'center', gap: 14 }}
            >
              <div style={{ width: 120, flex: '0 0 120px' }}>
                <span className="stamp">{ev.type.toUpperCase()}</span>
                <div className="ref" style={{ fontSize: 13 }}>
                  {ev.ref}
                </div>
              </div>
              <span className="grow" style={{ fontSize: 14 }}>
                {ev.title}
                <span className="m"> · {dateOnly(ev.date)}</span>
              </span>
              <button type="button" className="btn o" style={{ padding: '7px 12px', fontSize: 13 }}>
                Open source
              </button>
            </div>
          ))}
        </>
      ) : null}
    </div>
  );
}

function ApprovalPanel({
  comment,
  onComment,
  inFlight,
  onDecide,
  nextStepName,
}: {
  comment: string;
  onComment: (v: string) => void;
  inFlight: 'approve' | 'reject' | null;
  onDecide: (d: 'approve' | 'reject') => void;
  approvalId: string;
  nextStepName: string;
}) {
  const busy = inFlight !== null;

  return (
    <div className="card t" style={{ border: '2px solid var(--required-fg)' }}>
      <h3 style={{ fontSize: 18, marginBottom: 12 }}>Your decision</h3>

      <label className="lab" htmlFor="approval-comment" style={{ display: 'block', marginBottom: 6 }}>
        COMMENT (REQUIRED IF REJECTING)
      </label>
      <textarea
        id="approval-comment"
        className="inp"
        rows={3}
        value={comment}
        onChange={(e) => onComment(e.target.value)}
        disabled={busy}
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, margin: '14px 0' }}>
        <button
          type="button"
          className="btn big"
          disabled={busy}
          onClick={() => onDecide('approve')}
        >
          {inFlight === 'approve' ? 'Approving…' : 'Approve'}
        </button>
        <button
          type="button"
          className="btn big danger"
          disabled={busy}
          onClick={() => onDecide('reject')}
        >
          {inFlight === 'reject' ? 'Rejecting…' : 'Reject'}
        </button>
      </div>

      <div className="lab" style={{ marginBottom: 6 }}>
        WHAT HAPPENS NEXT
      </div>
      <p className="m" style={{ lineHeight: 1.6 }}>
        <b>If approved:</b> {nextStepName} runs automatically.
        <br />
        <b>If rejected:</b> the run stops and nothing is created.
        <br />
        Your name and the time are recorded with the decision.
      </p>
    </div>
  );
}
'use client';

import Link from 'next/link';
import { api } from '@/lib/api';
import { useResource } from '@/lib/useResource';
import { duration, metric, timestamp } from '@/lib/format';
import { ClassBadge } from '@/components/ClassBadge';
import { EmptyCard, ErrorCard, LoadingCard } from '@/components/States';
import { Breadcrumb } from '@/components/Chrome';
import type { WorkflowDetail as WorkflowData } from '@/lib/types';

/** Screen 2 — Workflow Detail. The discovered timeline of how the work actually flows. */
export function WorkflowDetail({ workflowId }: { workflowId: string }) {
  const wf = useResource((signal) => api.workflow(workflowId, signal), [workflowId]);

  return (
    <>
      <Breadcrumb
        items={[
          { label: 'Workflows', href: '/workflows' },
          { label: wf.status === 'success' ? wf.data.name : 'Workflow' },
        ]}
      />

      <div className="page">
        {wf.status === 'loading' ? <LoadingCard label="LOADING · WORKFLOW" lines={3} /> : null}

        {wf.status === 'error' ? (
          <ErrorCard
            error={wf.error}
            onRetry={wf.reload}
            title="This workflow could not be loaded."
          />
        ) : null}

        {wf.status === 'success' ? <WorkflowBody data={wf.data} workflowId={workflowId} /> : null}
      </div>
    </>
  );
}

function WorkflowBody({ data, workflowId }: { data: WorkflowData; workflowId: string }) {
  if (data.steps.length === 0) {
    return (
      <EmptyCard
        title="This workflow has no steps yet"
        detail="Steps appear once company events for this workflow have been analyzed."
      />
    );
  }

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
        <div>
          <h1 style={{ fontSize: 26 }}>{data.name}</h1>
          {data.description ? (
            <p className="m" style={{ marginTop: 6, maxWidth: 620 }}>
              {data.description}
            </p>
          ) : null}
        </div>
        <span className="bd n" style={{ height: 16 }}>
          DISCOVERED
        </span>
      </div>

      <div className="row" style={{ margin: '24px 0' }}>
        <Stat label="EXECUTIONS" value={metric(data.executions)} />
        <Stat label="AVG DURATION" value={duration(data.avg_duration_ms)} />
        <Stat label="LAST ACTIVITY" value={timestamp(data.last_activity_at)} />
        <Stat label="AUTOMATION POTENTIAL" value={metric(data.automation_potential)} />
      </div>

      <div className="card t">
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 20 }}>
          <h3 style={{ fontSize: 16 }}>How the work actually flows</h3>
          <span className="m">Select a step to see why it exists</span>
        </div>

        <Timeline workflowId={workflowId} steps={data.steps} />

        <div
          className="row"
          style={{ display: 'flex', justifyContent: 'space-between', marginTop: 20 }}
        >
          <Link className="btn o" href={`/workflows/${workflowId}/automation`}>
            Review automation
          </Link>
          <Link
            className="btn"
            href={`/workflows/${workflowId}/steps/${data.steps[0].step_id}`}
          >
            View step intelligence
          </Link>
        </div>
      </div>
    </>
  );
}

function Timeline({
  workflowId,
  steps,
}: {
  workflowId: string;
  steps: import('@/lib/types').Step[];
}) {
  return (
    <div className="tl" style={{ paddingBottom: 12 }}>
      {steps.map((s, i) => (
        <Link
          key={s.step_id}
          className="tl-step"
          href={`/workflows/${workflowId}/steps/${s.step_id}`}
        >
          <span className="tl-stem" style={{ left: '50%' }} aria-hidden="true" />
          <span className="tl-body">
            <span className={`num r${(i % 3) + 2}`} aria-hidden="true">
              {s.order}
            </span>
            <span className="tl-name">{s.name}</span>
            <ClassBadge value={s.automation_class} small />
          </span>
        </Link>
      ))}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card stat">
      <div className="lab">{label}</div>
      <h2 style={{ fontSize: 24, marginTop: 6 }}>{value}</h2>
    </div>
  );
}
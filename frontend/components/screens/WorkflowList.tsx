'use client';

import Link from 'next/link';
import { api } from '@/lib/api';
import { useResource } from '@/lib/useResource';
import { duration, metric, timestamp } from '@/lib/format';
import { EmptyCard, ErrorCard, LoadingCard } from '@/components/States';
import type { Dashboard } from '@/lib/types';

/** Workflow list — the entry point to the demo path. */
export function WorkflowList() {
  const dash = useResource((signal) => api.dashboard(signal), []);

  return (
    <>
      <div className="bc">
        <b>Workflows</b>
      </div>

      <div className="page">
        <h1 style={{ fontSize: 26 }}>Workflows</h1>
        <p className="m" style={{ margin: '6px 0 24px' }}>
          Workflows discovered from company events.
        </p>

        {dash.status === 'loading' ? <LoadingCard label="LOADING · WORKFLOWS" lines={3} /> : null}

        {dash.status === 'error' ? (
          <ErrorCard error={dash.error} onRetry={dash.reload} title="Workflows could not be loaded." />
        ) : null}

        {dash.status === 'success' ? <ListBody data={dash.data} /> : null}
      </div>
    </>
  );
}

function ListBody({ data }: { data: Dashboard }) {
  if (data.workflows.length === 0) {
    return (
      <EmptyCard
        title="No workflows discovered yet"
        detail="Workflows appear after company events are connected and analyzed."
      />
    );
  }

  return (
    <div className="card t" style={{ padding: 0 }}>
      <div className="row" style={{ padding: '12px 20px', gap: 16 }}>
        <span className="lab" style={{ width: 36 }}>
          #
        </span>
        <span className="lab" style={{ flex: '1 1 0%' }}>
          WORKFLOW
        </span>
        <span className="lab" style={{ width: 140 }}>
          EXECUTIONS
        </span>
        <span className="lab" style={{ width: 160 }}>
          AVG DURATION
        </span>
        <span className="lab" style={{ width: 200 }}>
          LAST ACTIVITY
        </span>
        <span className="lab" style={{ width: 150 }}>
          STATUS
        </span>
      </div>

      {data.workflows.map((wf, i) => (
        <div
          key={wf.workflow_id}
          className="row"
          style={{ padding: '14px 20px', gap: 16, alignItems: 'center' }}
        >
          <span style={{ width: 36 }}>
            <span className={`num r${(i % 3) + 2}`} style={{ fontSize: 13 }}>
              {i + 1}
            </span>
          </span>
          <div style={{ flex: '1 1 0%' }}>
            <Link
              href={`/workflows/${wf.workflow_id}`}
              style={{ fontWeight: 600, fontSize: 14, textDecoration: 'none' }}
            >
              {wf.name}
            </Link>
            {wf.category ? <div className="m">{wf.category}</div> : null}
          </div>
          <span style={{ width: 140 }} data-label="Executions">
            {metric(wf.executions)}
          </span>
          <span style={{ width: 160 }} data-label="Avg duration">
            {duration(wf.avg_duration_ms)}
          </span>
          <span style={{ width: 200 }} data-label="Last activity">
            {timestamp(wf.last_activity_at)}
          </span>
          <span style={{ width: 150 }} data-label="Status">
            <span className="bd n">DISCOVERED</span>
          </span>
        </div>
      ))}
    </div>
  );
}
'use client';

import Link from 'next/link';
import { api } from '@/lib/api';
import { useResource } from '@/lib/useResource';
import { duration, metric, timestamp } from '@/lib/format';
import { EmptyCard, ErrorCard, LoadingCard } from '@/components/States';
import type { Dashboard as DashboardData } from '@/lib/types';

/** Screen 1 — Dashboard. One API call: GET /dashboard. */
export function Dashboard() {
  const dash = useResource((signal) => api.dashboard(signal), []);

  return (
    <>
      <div className="bc">
        <b>Overview</b>
      </div>

      <div className="page">
        <h1 style={{ fontSize: 26 }}>Overview</h1>
        <p className="m" style={{ margin: '6px 0 24px' }}>
          What is happening across your company workflows.
        </p>

        {dash.status === 'loading' ? <LoadingCard label="LOADING · OVERVIEW" lines={2} /> : null}

        {dash.status === 'error' ? (
          <ErrorCard
            error={dash.error}
            onRetry={dash.reload}
            title="The overview could not be loaded."
          />
        ) : null}

        {dash.status === 'success' ? <DashboardBody data={dash.data} /> : null}
      </div>
    </>
  );
}

function DashboardBody({ data }: { data: DashboardData }) {
  const hasWorkflows = data.workflows.length > 0;

  return (
    <>
      <div className="row" style={{ marginBottom: 20 }}>
        <Stat
          label="WORKFLOWS DISCOVERED"
          value={metric(data.workflows_discovered)}
          note="From company events"
        />
        <Stat
          label="AUTOMATION OPPORTUNITIES"
          value={metric(data.automation_opportunities)}
          note="Steps that can run safely"
        />
        <Stat
          label="WORKFLOW EXECUTIONS"
          value={metric(data.workflow_executions)}
          note="Automated runs"
        />
        <Stat
          label="POTENTIAL TIME SAVED"
          value={duration(data.time_saved_ms)}
          note={
            data.time_saved_is_estimate
              ? 'Estimate — not a measured result'
              : 'Measured'
          }
        />
      </div>

      <div className="row">
        <div className="card t" style={{ flex: '1 1 0%' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 14 }}>
            <h3 style={{ fontSize: 16 }}>Discovered workflows</h3>
            <span className="m">{data.workflows.length} workflow(s)</span>
          </div>

          {!hasWorkflows ? (
            <EmptyCard
              title="No workflows discovered yet"
              detail="Workflows appear after company events are connected and analyzed."
            />
          ) : (
            data.workflows.map((wf, i) => (
              <div key={wf.workflow_id} className="ln" style={{ alignItems: 'center', gap: 16 }}>
                <div className={`num r${(i % 3) + 2}`} aria-hidden="true" style={{ fontSize: 13 }}>
                  {i + 1}
                </div>
                <div className="grow">
                  <b style={{ fontSize: 15 }}>{wf.name}</b>
                  <div className="m" style={{ marginTop: 4 }}>
                    Executions: {metric(wf.executions)} · Avg duration:{' '}
                    {duration(wf.avg_duration_ms)} · Last activity:{' '}
                    {timestamp(wf.last_activity_at)}
                  </div>
                </div>
                <span className="bd n">DISCOVERED</span>
                <Link className="btn o" href={`/workflows/${wf.workflow_id}`}>
                  Open workflow
                </Link>
              </div>
            ))
          )}

          {hasWorkflows ? (
            <p
              className="m"
              style={{ paddingTop: 14, background: 'var(--rule) center top / 100% 2px no-repeat' }}
            >
              More workflows appear here as they are discovered.
            </p>
          ) : null}
        </div>

        <div className="card t" style={{ width: 380 }}>
          <h3 style={{ fontSize: 16, marginBottom: 10 }}>Recent activity</h3>

          {data.recent_activity.length === 0 ? (
            <p
              className="m"
              style={{ paddingTop: 14, background: 'var(--rule) center top / 100% 2px no-repeat' }}
            >
              No activity recorded yet.
            </p>
          ) : (
            data.recent_activity.map((a, i) => (
              <div key={i} className="ln" style={{ alignItems: 'flex-start' }}>
                <span className="m" style={{ width: 52 }}>
                  {a.at ? timestamp(a.at) : '--:--'}
                </span>
                <span className="grow">
                  {a.label}
                  {a.workflow_name ? <div className="m">{a.workflow_name}</div> : null}
                </span>
              </div>
            ))
          )}

          <div
            className="row"
            style={{ gap: 8, paddingTop: 12, background: 'var(--rule) center top / 100% 2px no-repeat' }}
          >
            <Link className="btn o" style={{ padding: '6px 12px' }} href="/workflows">
              View all activity
            </Link>
          </div>
        </div>
      </div>
    </>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="card t stat">
      <div className="lab">{label}</div>
      <h2 style={{ fontSize: 26, margin: '6px 0' }}>{value}</h2>
      <div className="m">{note}</div>
    </div>
  );
}
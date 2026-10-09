'use client';

import Link from 'next/link';
import { api } from '@/lib/api';
import { useResource } from '@/lib/useResource';
import { metric } from '@/lib/format';
import { ClassBadge } from '@/components/ClassBadge';
import { EmptyCard } from '@/components/States';
import { Breadcrumb } from '@/components/Chrome';
import type { Analysis } from '@/lib/types';

const WORKFLOW_ID = 'wf_purchase_request';

/**
 * Automation — what is ready to run, what is waiting for a person, and what already ran.
 *
 * This is the list screen behind the "Automation" nav tab. The per-workflow analysis is
 * on /workflows/[id]/automation.
 */
export function AutomationList() {
  const analysis = useResource((signal) => api.analyze(WORKFLOW_ID, signal), []);
  const dash = useResource((signal) => api.dashboard(signal), []);

  return (
    <>
      <Breadcrumb items={[{ label: 'Automation' }]} />

      <div className="page">
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontSize: 26 }}>Automation</h1>
          <p className="m" style={{ marginTop: 6 }}>
            What is ready to run, what is waiting for you, and what already ran.
          </p>
        </div>

        <div className="row" style={{ marginBottom: 20, alignItems: 'flex-start' }}>
          <div className="card t" style={{ flex: '1 1 0%' }}>
            <h3 style={{ fontSize: 16, marginBottom: 12 }}>Needs your decision</h3>
            <NeedsDecision analysis={analysis} dash={dash} />
          </div>

          <div className="card t" style={{ flex: '1 1 0%' }}>
            <h3 style={{ fontSize: 16, marginBottom: 12 }}>Ready to automate</h3>
            <ReadyToAutomate analysis={analysis} />
          </div>
        </div>

        <div className="card t" style={{ padding: 0 }}>
          <div style={{ padding: '18px 20px 12px' }}>
            <h3 style={{ fontSize: 16 }}>Automation runs</h3>
          </div>
          <RunsTable dash={dash} />
        </div>
      </div>
    </>
  );
}

function NeedsDecision({
  analysis,
  dash,
}: {
  analysis: ReturnType<typeof useResource<Analysis>>;
  dash: ReturnType<typeof useResource<import('@/lib/types').Dashboard>>;
}) {
  if (analysis.status === 'loading' || dash.status === 'loading') {
    return (
      <div style={{ paddingTop: 4 }}>
        <div className="sk" style={{ width: '70%' }} />
        <div className="sk" style={{ width: '50%' }} />
      </div>
    );
  }

  if (analysis.status === 'error') {
    return <p className="m">The analysis could not be loaded.</p>;
  }

  const required = analysis.data.steps.filter((s) => s.automation_class === 'HUMAN_REQUIRED');

  if (required.length === 0) {
    return (
      <p className="m">
        No step in this workflow requires a human decision.
      </p>
    );
  }

  const workflows = dash.status === 'success' ? dash.data.workflows : [];

  return (
    <>
      {required.map((s) => {
        const wf = workflows[0];
        return (
          <div
            key={s.step_id}
            className="row"
            style={{ gap: 12, alignItems: 'center', padding: '14px 0' }}
          >
            <div className="grow">
              <b style={{ fontSize: 14 }}>{wf?.name ?? 'Workflow'}</b>
              <div className="m" style={{ margin: '4px 0 8px' }}>
                {s.name} · no decision recorded yet
              </div>
              <ClassBadge value={s.automation_class} />
            </div>
            <Link
              className="btn small"
              href={`/workflows/${WORKFLOW_ID}/automation`}
            >
              Review and decide
            </Link>
          </div>
        );
      })}
    </>
  );
}

function ReadyToAutomate({ analysis }: { analysis: ReturnType<typeof useResource<Analysis>> }) {
  if (analysis.status === 'loading') {
    return (
      <div style={{ paddingTop: 4 }}>
        <div className="sk" style={{ width: '80%' }} />
        <div className="sk" style={{ width: '60%' }} />
      </div>
    );
  }

  if (analysis.status === 'error') {
    return <p className="m">The analysis could not be loaded.</p>;
  }

  const { safe, human_review, human_required } = analysis.data.summary;

  return (
    <div className="row" style={{ gap: 12, alignItems: 'center', padding: '14px 0' }}>
      <div className="grow">
        <b style={{ fontSize: 14 }}>Purchase Request Processing</b>
        <div className="m" style={{ marginTop: 4 }}>
          {metric(safe)} safe · {metric(human_review)} need review ·{' '}
          {metric(human_required)} require a human
        </div>
      </div>
      <Link className="btn o small" href={`/workflows/${WORKFLOW_ID}/automation`}>
        Review analysis
      </Link>
    </div>
  );
}

/**
 * Run history. The API contract has no run-list endpoint, so this lists what the
 * dashboard reports and does not invent runs. Live runs are opened from the run screen.
 */
function RunsTable({
  dash,
}: {
  dash: ReturnType<typeof useResource<import('@/lib/types').Dashboard>>;
}) {
  if (dash.status === 'loading') {
    return (
      <div style={{ padding: '0 20px 16px' }}>
        <div className="sk" style={{ width: '90%' }} />
        <div className="sk" style={{ width: '70%' }} />
      </div>
    );
  }

  if (dash.status === 'error') {
    return (
      <div style={{ padding: '0 20px 16px' }}>
        <p className="m">Runs could not be loaded.</p>
      </div>
    );
  }

  const executions = dash.data.workflow_executions;

  if (executions === null || executions === 0) {
    return (
      <div style={{ padding: '0 20px 16px' }}>
        <EmptyCard
          title="No automation runs yet"
          detail="Runs appear here after automation is started on a workflow."
          actions={
            <Link className="btn small" href={`/workflows/${WORKFLOW_ID}/automation`}>
              Start a run
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <>
      <div className="row" style={{ gap: 16, padding: '0 20px 10px' }}>
        <span className="lab" style={{ width: 100 }}>RUN</span>
        <span className="lab" style={{ width: 260 }}>WORKFLOW</span>
        <span className="lab" style={{ width: 210 }}>STATUS</span>
        <span className="lab" style={{ width: 130 }}>STARTED</span>
        <span className="lab" style={{ width: 100 }}>DURATION</span>
      </div>
      <p className="m" style={{ padding: '14px 20px' }}>
        Run history rows require a run-list endpoint, which the API contract does not define.
        Open a workflow to start or inspect a run.
      </p>
    </>
  );
}
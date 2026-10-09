'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { api } from '@/lib/api';
import { useResource } from '@/lib/useResource';
import { confidence } from '@/lib/format';
import { ClassBadge } from '@/components/ClassBadge';
import { EmptyCard, ErrorCard, LoadingCard } from '@/components/States';
import { Breadcrumb } from '@/components/Chrome';
import type { Analysis, AutomationClass } from '@/lib/types';

/**
 * Screen 4 — Automation Analysis.
 *
 * Every step is classified SAFE / HUMAN REVIEW / HUMAN REQUIRED with a text label and a
 * distinct glyph — never colour alone. The screen must visibly communicate that AI is
 * not replacing human judgment.
 */
export function AutomationAnalysis({ workflowId }: { workflowId: string }) {
  const router = useRouter();

  const analysis = useResource((signal) => api.analyze(workflowId, signal), [workflowId]);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<unknown>(null);

  async function startRun() {
    setStarting(true);
    setStartError(null);
    try {
      const run = await api.startRun(workflowId);
      router.push(`/workflows/${workflowId}/automation/run/${run.run_id}`);
    } catch (err) {
      setStartError(err);
      setStarting(false);
    }
  }

  return (
    <>
      <Breadcrumb
        items={[
          { label: 'Automation', href: `/workflows/${workflowId}/automation` },
          { label: 'Workflow', href: `/workflows/${workflowId}` },
          { label: 'Analysis' },
        ]}
      />

      <div className="page">
        <h1 style={{ fontSize: 26 }}>Automation analysis</h1>
        <p className="m" style={{ margin: '6px 0 24px' }}>
          What can run on its own, and where a person stays in control.
        </p>

        {analysis.status === 'loading' ? <LoadingCard label="LOADING · ANALYSIS" lines={4} /> : null}

        {analysis.status === 'error' ? (
          <ErrorCard
            error={analysis.error}
            onRetry={analysis.reload}
            title="The analysis could not be loaded."
          />
        ) : null}

        {analysis.status === 'success' ? (
          <AnalysisBody
            data={analysis.data}
            starting={starting}
            startError={startError}
            onStart={startRun}
          />
        ) : null}
      </div>
    </>
  );
}

function AnalysisBody({
  data,
  starting,
  startError,
  onStart,
}: {
  data: Analysis;
  starting: boolean;
  startError: unknown;
  onStart: () => void;
}) {
  if (data.steps.length === 0) {
    return (
      <EmptyCard
        title="No steps were classified"
        detail="Analysis returns a class for every step. An empty result means the workflow has not been analyzed yet."
      />
    );
  }

  const firstHumanRequired = data.steps.find(
    (s) => s.automation_class === 'HUMAN_REQUIRED',
  );

  return (
    <>
      <div className="row" style={{ marginBottom: 20 }}>
        <SummaryCard label="SAFE" tone="s" value={data.summary.safe} />
        <SummaryCard label="HUMAN REVIEW" tone="r" value={data.summary.human_review} />
        <SummaryCard label="HUMAN REQUIRED" tone="q" value={data.summary.human_required} />
      </div>

      <div className="card t" style={{ padding: 0 }}>
        <div className="row" style={{ padding: '12px 20px', gap: 16 }}>
          <span className="lab" style={{ width: 36 }}>
            #
          </span>
          <span className="lab" style={{ width: 260 }}>
            STEP
          </span>
          <span className="lab" style={{ width: 170 }}>
            STATUS
          </span>
          <span className="lab">WHAT HAPPENS</span>
        </div>

        {data.steps.map((s, i) => (
          <div
            key={s.step_id}
            className="row"
            style={{ padding: '14px 20px', gap: 16, alignItems: 'flex-start' }}
          >
            <span style={{ width: 36 }}>
              <span className={`num r${(i % 3) + 2}`} style={{ fontSize: 13 }}>
                {i + 1}
              </span>
            </span>
            <div style={{ width: 260 }}>
              <Link
                href={`/workflows/${data.workflow_id}/steps/${s.step_id}`}
                style={{ fontWeight: 600, fontSize: 14, textDecoration: 'none' }}
              >
                {s.name}
              </Link>
              <div className="m" style={{ marginTop: 4, fontSize: 12 }}>
                Confidence {confidence(s.confidence)}
              </div>
            </div>
            <span style={{ width: 170 }}>
              <ClassBadge value={s.automation_class} />
            </span>
            <div className="grow">
              <span className="m">{s.reason ?? 'No reason was returned for this step.'}</span>
            </div>
          </div>
        ))}

        <div
          className="row"
          style={{
            justifyContent: 'space-between',
            alignItems: 'center',
            marginTop: 20,
            padding: '16px 20px 0',
            borderTop: '2px solid var(--border)',
          }}
        >
          <span className="m">
            {firstHumanRequired
              ? `The run will pause at ${firstHumanRequired.name} until a manager decides.`
              : 'No step requires a human decision.'}
          </span>
          <button
            type="button"
            className="btn"
            onClick={onStart}
            disabled={starting}
            style={{ marginTop: 16, marginBottom: 20 }}
          >
            {starting ? 'Starting…' : 'Run automation'}
          </button>
        </div>
      </div>

      {startError ? (
        <div style={{ marginTop: 16 }}>
          <ErrorCard
            error={startError}
            onRetry={onStart}
            title="Automation stopped because a step failed."
            extraActions={
              <Link className="btn o small" href={`/workflows/${data.workflow_id}/automation/run`}>
                View run
              </Link>
            }
          />
        </div>
      ) : null}

      <p className="m" style={{ marginTop: 16, maxWidth: 680 }}>
        Rules version {data.policy_rules_version}. The backend enforces these classes; this
        screen only reflects them.
      </p>
    </>
  );
}

function SummaryCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div className="card t stat">
      <div className="lab" style={{ marginBottom: 10 }}>
        {label}
      </div>
      <div className="row" style={{ alignItems: 'center', gap: 12 }}>
        <h2 style={{ fontSize: 26 }}>{value}</h2>
        <span className={`bd ${tone}`} aria-hidden="true">
          {label}
        </span>
      </div>
      <div className="m" style={{ marginTop: 8 }}>
        {describeClass(label as AutomationClass)}
      </div>
    </div>
  );
}

function describeClass(kind: AutomationClass): string {
  switch (kind) {
    case 'SAFE':
      return 'Deterministic and reversible — runs automatically.';
    case 'HUMAN_REVIEW':
      return 'The system prepares findings; a person confirms.';
    case 'HUMAN_REQUIRED':
      return 'Judgment or financial commitment — execution stops.';
    default:
      return '';
  }
}
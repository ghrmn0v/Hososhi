'use client';

import Link from 'next/link';
import { api } from '@/lib/api';
import { useResource } from '@/lib/useResource';
import {
  NOT_MEASURED,
  delta,
  duration,
  metric,
  percent,
  sourceLabel,
  timestamp,
} from '@/lib/format';
import { EmptyCard, ErrorCard, LoadingCard } from '@/components/States';
import { Breadcrumb } from '@/components/Chrome';
import type { MetricsBlock, Results as ResultsData } from '@/lib/types';

type MetricKey = Exclude<keyof Omit<MetricsBlock, 'label' | 'source'>, never>;

const ROWS: { key: MetricKey; label: string; render: (v: number | null) => string }[] = [
  { key: 'total_duration_ms', label: 'Processing time', render: duration },
  { key: 'manual_steps', label: 'Manual steps', render: metric },
  { key: 'human_decisions', label: 'Human interventions', render: metric },
  { key: 'automation_rate', label: 'Automation rate', render: percent },
  { key: 'errors', label: 'Errors / exceptions', render: metric },
];

/**
 * Screen 6 — Results.
 *
 * The hard rule lives here: a metric that is null renders as the text "not measured".
 * Never 0, never a placeholder, never a hardcoded claim. Each block shows its `source`
 * so every number is visibly grounded.
 */
export function Results({
  workflowId,
  runId,
}: {
  workflowId: string;
  runId: string;
}) {

  const res = useResource((signal) => api.results(runId, signal), [runId]);

  return (
    <>
      <Breadcrumb
        items={[
          { label: 'Automation', href: `/workflows/${workflowId}/automation` },
          { label: 'Workflow', href: `/workflows/${workflowId}` },
          { label: 'Run', href: `/workflows/${workflowId}/automation/run/${runId}` },
          { label: 'Results' },
        ]}
      />

      <div className="page">
        <h1 style={{ fontSize: 26, margin: '8px 0 24px' }}>Results: original vs AI-assisted</h1>

        {res.status === 'loading' ? <LoadingCard label="LOADING · RESULTS" lines={4} /> : null}

        {res.status === 'error' ? (
          <ErrorCard
            error={res.error}
            onRetry={res.reload}
            title="Results could not be loaded."
            extraActions={
              <Link className="btn o small" href={`/workflows/${workflowId}/automation/run/${runId}`}>
                Back to run
              </Link>
            }
          />
        ) : null}

        {res.status === 'success' ? <ResultsBody data={res.data} /> : null}
      </div>
    </>
  );
}

function ResultsBody({ data }: { data: ResultsData }) {
  const nothingMeasured =
    !data.is_measured &&
    data.baseline.total_duration_ms === null &&
    data.ai_assisted.total_duration_ms === null;

  return (
    <>
      <div className="card t" style={{ padding: 0 }}>
        <div className="row" style={{ padding: '12px 20px', gap: 16 }}>
          <span className="lab" style={{ width: 280 }}>
            METRIC
          </span>
          <span className="lab" style={{ width: 220 }}>
            ORIGINAL
          </span>
          <span className="lab" style={{ width: 220 }}>
            AI-ASSISTED
          </span>
          <span className="lab">DIFFERENCE</span>
        </div>

        {ROWS.map((row) => {
          const base = data.baseline[row.key];
          const ai = data.ai_assisted[row.key];
          return (
            <div
              key={row.key}
              className="row"
              style={{ padding: '14px 20px', gap: 16, alignItems: 'baseline' }}
            >
              <b style={{ width: 280 }} data-label="Metric">
                {row.label}
              </b>
              <span style={{ width: 220 }} data-label={data.baseline.label}>
                {row.render(base)}
              </span>
              <span style={{ width: 220 }} data-label={data.ai_assisted.label}>
                {row.render(ai)}
              </span>
              <span className="m grow" data-label="Difference">
                {differenceFor(row.key, base, ai)}
              </span>
            </div>
          );
        })}
      </div>

      <div className="row" style={{ marginTop: 20, alignItems: 'flex-start' }}>
        <div className="card" style={{ flex: '1 1 0%' }}>
          <div className="lab" style={{ marginBottom: 8 }}>
            WHERE THESE NUMBERS COME FROM
          </div>
          <p className="m" style={{ lineHeight: 1.7 }}>
            <b>{data.baseline.label}</b> — {sourceLabel(data.baseline.source)}.
            <br />
            <b>{data.ai_assisted.label}</b> — {sourceLabel(data.ai_assisted.source)}.
            <br />
            {data.measurement_method ?? 'No measurement method was returned by the API.'}
          </p>
          <p className="m" style={{ marginTop: 10, lineHeight: 1.7 }}>
            Runs counted: {metric(data.runs_count)} · Measured at{' '}
            {timestamp(data.measured_at)}
          </p>
        </div>

        <div className="card" style={{ width: 380, flex: '0 0 380px' }}>
          <div className="lab" style={{ marginBottom: 8 }}>
            DELTA
          </div>
          <DeltaRow label="Duration" value={deltaMs(data.delta.duration_ms)} />
          <DeltaRow label="Duration %" value={deltaPercent(data.delta.duration_percent)} />
          <DeltaRow
            label="Human interventions"
            value={delta(data.delta.human_interventions)}
          />
        </div>
      </div>

      {nothingMeasured ? (
        <div style={{ marginTop: 20 }}>
          <EmptyCard
            title="No results have been measured yet"
            detail={`A value is shown as “${NOT_MEASURED}” until the backend records one. Run a measured baseline first — nothing here is estimated.`}
          />
        </div>
      ) : null}

      <p className="m" style={{ marginTop: 16, maxWidth: 680 }}>
        Values come from recorded measurements. Better, worse or unchanged results are all
        shown as they are.
      </p>
    </>
  );
}

function DeltaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="ln first" style={{ justifyContent: 'space-between' }}>
      <span>{label}</span>
      <span className="m">{value}</span>
    </div>
  );
}

/** Difference is only shown when both sides were actually measured. */
function differenceFor(
  key: MetricKey,
  base: number | null,
  ai: number | null,
): string {
  if (base === null || ai === null) return NOT_MEASURED;
  const d = ai - base;
  const sign = d > 0 ? '+' : '';
  return key === 'automation_rate' ? `${sign}${Math.round(d * 100)} pts` : `${sign}${d}`;
}

function deltaMs(value: number | null): string {
  if (value === null) return NOT_MEASURED;
  return duration(value);
}

function deltaPercent(value: number | null): string {
  if (value === null) return NOT_MEASURED;
  const sign = value > 0 ? '+' : '';
  return `${sign}${value}%`;
}
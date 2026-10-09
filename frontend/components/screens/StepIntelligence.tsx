'use client';

import Link from 'next/link';
import { api } from '@/lib/api';
import { useResource } from '@/lib/useResource';
import { confidence, dateOnly } from '@/lib/format';
import { ClassBadge } from '@/components/ClassBadge';
import { EmptyCard, ErrorCard, LoadingCard } from '@/components/States';
import { Breadcrumb } from '@/components/Chrome';
import type { Evidence, EvidenceType, Intelligence } from '@/lib/types';

type IntelResource = ReturnType<typeof useResource<Intelligence>>;

/**
 * Screen 3 — Step Intelligence. The important screen.
 *
 * "Why does this step exist?" and the answer are visible on open: the demo must never
 * depend on a click landing. The step detail and the AI call are loaded independently
 * so an AI failure leaves the step on screen (partial state) instead of blanking it.
 */
export function StepIntelligence({
  workflowId,
  stepId,
}: {
  workflowId: string;
  stepId: string;
}) {
  const step = useResource((signal) => api.step(workflowId, stepId, signal), [
    workflowId,
    stepId,
  ]);
  const intel = useResource((signal) => api.intelligence(workflowId, stepId, signal), [
    workflowId,
    stepId,
  ]);

  return (
    <>
      <Breadcrumb
        items={[
          { label: 'Workflows', href: '/workflows' },
          { label: 'Workflow', href: `/workflows/${workflowId}` },
          { label: step.status === 'success' ? step.data.name : 'Step' },
        ]}
      />

      <div className="page">
        <h1 style={{ fontSize: 26, margin: '8px 0 24px' }}>
          {step.status === 'success' ? step.data.name : 'Step'}
        </h1>

        <div className="row">
          <div style={{ width: 300, flex: '0 0 300px' }}>
            {step.status === 'loading' ? <LoadingCard label="LOADING · STEP" lines={2} /> : null}

            {step.status === 'error' ? (
              <ErrorCard
                error={step.error}
                onRetry={step.reload}
                title="This step could not be loaded."
              />
            ) : null}

            {step.status === 'success' ? (
              <div className="card t">
                <div className="lab">STEP</div>
                <p style={{ margin: '8px 0 16px', fontSize: 14 }}>
                  {step.data.description ?? 'No description was returned for this step.'}
                </p>

                <div className="lab">AUTOMATION</div>
                <div style={{ margin: '8px 0 16px' }}>
                  <ClassBadge value={step.data.automation_class} />
                </div>

                <div className="lab">STATUS</div>
                <p style={{ marginTop: 8, fontSize: 14 }}>Observed in discovered workflow</p>

                <div style={{ marginTop: 20 }}>
                  <Link className="btn o small" href={`/workflows/${workflowId}`}>
                    Back to timeline
                  </Link>
                </div>
              </div>
            ) : null}
          </div>

          <div style={{ flex: '1 1 0%' }}>
            <Explanation intel={intel} workflowId={workflowId} />
          </div>
        </div>
      </div>
    </>
  );
}

function Explanation({
  intel,
  workflowId,
}: {
  intel: IntelResource;
  workflowId: string;
}) {
  if (intel.status === 'loading') {
    return <LoadingCard label="LOADING · EXPLANATION" lines={4} />;
  }

  if (intel.status === 'error') {
    // Partial state: the step panel beside this stays visible.
    return (
      <ErrorCard
        error={intel.error}
        onRetry={intel.reload}
        title="AI analysis is temporarily unavailable."
        fallbackDetail="The step itself is still shown. Try again, or continue without the explanation."
        extraActions={
          <Link className="btn o small" href={`/workflows/${workflowId}/automation`}>
            Continue without AI
          </Link>
        }
      />
    );
  }

  const data = intel.data;
  const stepId = data.step_id;

  return (
    <>
      <div className="card t">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ fontSize: 18 }}>{data.question}</h2>
          <Confidence value={data.confidence} />
        </div>

        <div className="m" style={{ margin: '6px 0 14px' }}>
          AI explanation · based on {data.evidence.length} company source
          {data.evidence.length === 1 ? '' : 's'}
          {data.model ? ` · ${data.model}` : ''}
          {data.fallback_used ? ' · fallback response' : ''}
        </div>

        {data.answer ? (
          <>
            {data.summary ? (
              <p style={{ fontSize: 15, fontWeight: 600, marginBottom: 8, lineHeight: 1.6 }}>
                {data.summary}
              </p>
            ) : null}
            <p style={{ fontSize: 15, lineHeight: 1.6 }}>{data.answer}</p>
          </>
        ) : (
          <EmptyCard
            title="No explanation was returned for this step"
            detail="The workflow data is still available. Treat this step as unexplained rather than accepting a guess."
            actions={
              <button type="button" className="btn small" onClick={intel.reload}>
                Ask again
              </button>
            }
          />
        )}
      </div>

      <EvidencePanel workflowId={workflowId} stepId={stepId} />
    </>
  );
}

function EvidencePanel({ workflowId, stepId }: { workflowId: string; stepId: string }) {
  const evidence = useResource(
    (signal) => api.evidence(workflowId, { step_id: stepId }, signal),
    [workflowId, stepId],
  );

  const items = evidence.status === 'success' ? evidence.data : [];

  return (
    <div className="card t" style={{ marginTop: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <h3 style={{ fontSize: 15 }}>
          Supporting evidence{evidence.status === 'success' ? ` (${items.length})` : ''}
        </h3>
        <span className="m">Traceable to company records</span>
      </div>

      {evidence.status === 'loading' ? (
        <div style={{ padding: '14px 0' }}>
          <div className="sk" style={{ width: '90%' }} />
          <div className="sk" style={{ width: '70%' }} />
          <div className="sk" style={{ width: '80%' }} />
        </div>
      ) : null}

      {evidence.status === 'error' ? (
        <ErrorCard
          error={evidence.error}
          onRetry={evidence.reload}
          title="Supporting evidence could not be loaded."
        />
      ) : null}

      {evidence.status === 'success' && items.length === 0 ? (
        <EmptyCard
          title="No supporting evidence was found"
          detail="The explanation is shown without sources. Treat it as unverified."
        />
      ) : null}

      {evidence.status === 'success' && items.length > 0
        ? groupByType(items).map(([, list]) => (
            <div key={list[0].type}>
              {list.map((ev) => (
                <EvidenceRow key={`${ev.type}-${ev.ref}`} ev={ev} />
              ))}
            </div>
          ))
        : null}
    </div>
  );
}

function EvidenceRow({ ev }: { ev: Evidence }) {
  return (
    <div className="ln" style={{ alignItems: 'flex-start' }}>
      <div style={{ width: 130, flex: '0 0 130px' }}>
        <span className="stamp">{typeLabel(ev.type)}</span>
        <div className="ref">{ev.ref}</div>
      </div>
      <div className="grow">
        <div style={{ fontWeight: 600, fontSize: 14 }}>{ev.title}</div>
        {ev.snippet ? (
          <div className="m" style={{ marginTop: 4 }}>
            {ev.snippet}
          </div>
        ) : null}
        <div className="m" style={{ marginTop: 4, fontSize: 12 }}>
          Relevance {confidence(ev.relevance)} · {dateOnly(ev.date)}
        </div>
      </div>
      <button type="button" className="btn o" style={{ padding: '6px 12px', height: 34 }}>
        Open source
      </button>
    </div>
  );
}

function Confidence({ value }: { value: number | null }) {
  const bars = value === null ? 0 : value >= 0.75 ? 3 : value >= 0.5 ? 2 : 1;

  return (
    <div className="conf">
      <span className={`meter${bars === 0 ? ' off' : ''}`} aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <b>
        {bars === 3
          ? 'High confidence'
          : bars === 2
            ? 'Medium confidence'
            : bars === 1
              ? 'Low confidence'
              : 'Confidence not reported'}
      </b>
      <span className="m">({confidence(value)})</span>
    </div>
  );
}

function groupByType(items: Evidence[]): [EvidenceType, Evidence[]][] {
  const order: EvidenceType[] = ['policy', 'decision', 'incident', 'event'];
  const map = new Map<EvidenceType, Evidence[]>();
  for (const ev of items) {
    const list = map.get(ev.type) ?? [];
    list.push(ev);
    map.set(ev.type, list);
  }
  return order.filter((t) => map.has(t)).map((t) => [t, map.get(t) as Evidence[]]);
}

function typeLabel(type: EvidenceType): string {
  switch (type) {
    case 'policy':
      return 'POLICY';
    case 'decision':
      return 'DECISION';
    case 'incident':
      return 'INCIDENT';
    case 'event':
      return 'EVENT';
    default:
      return String(type).toUpperCase();
  }
}
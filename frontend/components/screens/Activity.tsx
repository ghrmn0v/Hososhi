'use client';

import { useState } from 'react';
import { api } from '@/lib/api';
import { useResource } from '@/lib/useResource';
import { clockTime } from '@/lib/format';
import { EmptyCard, ErrorCard, LoadingCard } from '@/components/States';
import { Breadcrumb } from '@/components/Chrome';
import type { DashboardActivity } from '@/lib/types';

type Filter = 'all' | 'approvals' | 'runs' | 'discovery';

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'approvals', label: 'Approvals' },
  { id: 'runs', label: 'Runs' },
  { id: 'discovery', label: 'Discovery' },
];

/** Activity — everything that happened across workflows, newest first. */
export function Activity() {
  const dash = useResource((signal) => api.dashboard(signal), []);
  const [filter, setFilter] = useState<Filter>('all');

  return (
    <>
      <Breadcrumb items={[{ label: 'Activity' }]} />

      <div className="page">
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            marginBottom: 24,
          }}
        >
          <div>
            <h1 style={{ fontSize: 26 }}>Activity</h1>
            <p className="m" style={{ marginTop: 6 }}>
              Everything that happened across your workflows, newest first.
            </p>
          </div>
          <div className="row" style={{ gap: 8 }}>
            {FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                className={`btn small ${filter === f.id ? '' : 'o'}`}
                aria-pressed={filter === f.id}
                onClick={() => setFilter(f.id)}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {dash.status === 'loading' ? <LoadingCard label="LOADING · ACTIVITY" lines={4} /> : null}

        {dash.status === 'error' ? (
          <ErrorCard error={dash.error} onRetry={dash.reload} title="Activity could not be loaded." />
        ) : null}

        {dash.status === 'success' ? (
          <ActivityList items={dash.data.recent_activity} filter={filter} />
        ) : null}
      </div>
    </>
  );
}

function ActivityList({ items, filter }: { items: DashboardActivity[]; filter: Filter }) {
  const filtered = items.filter((a) => matches(a, filter));

  if (items.length === 0) {
    return (
      <div className="card t" style={{ padding: 0 }}>
        <EmptyCard
          title="No activity recorded yet"
          detail="Activity appears once workflows are discovered and automation runs start."
        />
      </div>
    );
  }

  if (filtered.length === 0) {
    return (
      <div className="card t" style={{ padding: 0 }}>
        <EmptyCard
          title="Nothing in this filter"
          detail={`No activity matches “${FILTERS.find((f) => f.id === filter)?.label}”. Choose another filter to see the rest.`}
          actions={
            <span className="m">{items.length} event(s) recorded in total.</span>
          }
        />
      </div>
    );
  }

  return (
    <div className="card t" style={{ padding: 0 }}>
      <div className="lab" style={{ padding: '16px 20px 8px' }}>RECENT</div>
      {filtered.map((a, i) => {
        const visual = visualFor(a.label);
        return (
          <div
            key={`${a.at}-${i}`}
            className="row"
            style={{ gap: 14, alignItems: 'center', padding: '13px 20px' }}
          >
            <span className="m" style={{ width: 50 }}>
              {clockTime(a.at)}
            </span>
            <div className="num r4" aria-hidden="true">
              {visual}
            </div>
            <span style={{ flex: '1 1 0%' }}>
              <b style={{ fontWeight: 600 }}>{a.label}</b>
              {a.workflow_name ? <div className="m">{a.workflow_name}</div> : null}
            </span>
          </div>
        );
      })}
      <p className="m" style={{ padding: '14px 20px' }}>
        {filtered.length} of {items.length} event(s) shown.
      </p>
    </div>
  );
}

/** Glyph per activity kind. The label carries the meaning, not the glyph. */
function visualFor(label: string): string {
  const l = label.toLowerCase();
  if (l.includes('approval')) return '!';
  if (l.includes('reject')) return '✗';
  if (l.includes('run started')) return '▶';
  if (l.includes('workflow')) return '↻';
  return '✓';
}

/** Filter matching is on the label the API returned; no category is invented here. */
function matches(a: DashboardActivity, filter: Filter): boolean {
  const l = a.label.toLowerCase();
  switch (filter) {
    case 'approvals':
      return l.includes('approval') || l.includes('reject');
    case 'runs':
      return l.includes('run');
    case 'discovery':
      return l.includes('workflow') || l.includes('discover');
    case 'all':
    default:
      return true;
  }
}
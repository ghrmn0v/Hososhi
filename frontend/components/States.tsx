import { ApiError } from '@/lib/errors';

/**
 * Loading / empty / error states.
 *
 * A blank screen is a defect. Every screen uses these so the four required states
 * (loading, error, empty, partial) exist everywhere without per-screen invention.
 */

type Tone = 'busy' | 'empty' | 'error' | 'wait';

const TONE_CLASS: Record<Tone, string> = {
  busy: 'num',
  empty: 'num pending',
  error: 'num wait',
  wait: 'num review',
};

const TONE_GLYPH: Record<Tone, string> = {
  busy: '…',
  empty: '—',
  error: '!',
  wait: 'II',
};

const TONE_COLOR: Record<Tone, string> = {
  busy: 'var(--indigo)',
  empty: 'var(--muted)',
  error: 'var(--accent)',
  wait: 'var(--review-fg)',
};

export function StateCard({
  tone,
  label,
  title,
  detail,
  actions,
}: {
  tone: Tone;
  label: string;
  title: string;
  detail?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="card t state">
      <div className="lab" style={{ marginBottom: 12 }}>
        {label}
      </div>
      <div className="state-icon">
        <div className={`${TONE_CLASS[tone]} r3`} style={{ borderColor: TONE_COLOR[tone], color: TONE_COLOR[tone] }}>
          {TONE_GLYPH[tone]}
        </div>
        <div>
          <h3>{title}</h3>
          {detail ? <p className="m" style={{ marginTop: 6, lineHeight: 1.5 }}>{detail}</p> : null}
        </div>
      </div>
      {actions ? <div className="state-actions">{actions}</div> : null}
    </div>
  );
}

export function SkeletonLines({ count = 3 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="sk" style={{ width: `${90 - i * 10}%` }} />
      ))}
    </>
  );
}

/** Full-card loading state that matches the shape of the content it replaces. */
export function LoadingCard({ label, lines = 3 }: { label: string; lines?: number }) {
  return (
    <div className="card t state">
      <div className="lab" style={{ marginBottom: 12 }}>
        {label}
      </div>
      <div className="state-icon">
        <div className="num r3" style={{ borderColor: 'var(--indigo)', color: 'var(--indigo)' }}>
          …
        </div>
        <div style={{ flex: 1 }}>
          <h3>Loading…</h3>
          <p className="m" style={{ marginTop: 6, lineHeight: 1.5 }}>
            This can take a moment.
          </p>
        </div>
      </div>
      <div style={{ marginTop: 14 }}>
        <SkeletonLines count={lines} />
      </div>
    </div>
  );
}

/**
 * Error state with a Retry action and the request id when the API supplied one.
 * No red-alert shouting — a plain readable message and a next step.
 */
export function ErrorCard({
  error,
  onRetry,
  title = 'This could not be loaded.',
  fallbackDetail = 'Check your connection and try again. Your data has not changed.',
  extraActions,
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
  fallbackDetail?: string;
  extraActions?: React.ReactNode;
}) {
  const isApi = error instanceof ApiError;
  const detail = isApi ? error.message : fallbackDetail;

  return (
    <div className="card t state">
      <div className="lab" style={{ marginBottom: 12 }}>
        ERROR
      </div>
      <div className="state-icon">
        <div className="num wait r3" style={{ borderColor: 'var(--accent)', color: 'var(--accent)' }}>
          !
        </div>
        <div>
          <h3>{title}</h3>
          <p className="m" style={{ marginTop: 6, lineHeight: 1.5 }}>
            {detail}
          </p>
          {isApi && error.requestId ? (
            <p className="m" style={{ marginTop: 8, fontSize: 12 }}>
              Request <code>{error.requestId}</code>
            </p>
          ) : null}
        </div>
      </div>
      <div className="state-actions">
        {onRetry ? (
          <button type="button" className="btn small" onClick={onRetry}>
            Try again
          </button>
        ) : null}
        {extraActions}
      </div>
    </div>
  );
}

/** Empty state with a real sentence, never an empty container. */
export function EmptyCard({
  title,
  detail,
  actions,
}: {
  title: string;
  detail: string;
  actions?: React.ReactNode;
}) {
  return (
    <StateCard tone="empty" label="EMPTY" title={title} detail={detail} actions={actions} />
  );
}
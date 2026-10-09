import type { AutomationClass } from '@/lib/types';
import { isClass } from '@/lib/format';

/**
 * The three automation classes are always shown with a text label plus a distinct
 * icon. Colour alone is never the signal — it has to survive a projector and a
 * colour-blind viewer.
 */

const LABEL: Record<AutomationClass, string> = {
  SAFE: 'SAFE',
  HUMAN_REVIEW: 'HUMAN REVIEW',
  HUMAN_REQUIRED: 'HUMAN REQUIRED',
};

const TONE: Record<AutomationClass, string> = {
  SAFE: 's',
  HUMAN_REVIEW: 'r',
  HUMAN_REQUIRED: 'q',
};

function Glyph({ kind }: { kind: AutomationClass }) {
  const common = {
    width: 12,
    height: 12,
    viewBox: '0 0 12 12',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
  } as const;

  if (kind === 'SAFE') {
    return (
      <svg {...common} aria-hidden="true">
        <path d="M2 6.5l3 3 5-6" />
      </svg>
    );
  }
  if (kind === 'HUMAN_REVIEW') {
    return (
      <svg {...common} aria-hidden="true">
        <circle cx="6" cy="6" r="2" />
        <path d="M1 6s2-4 5-4 5 4 5 4-2 4-5 4-5-4-5-4z" />
      </svg>
    );
  }
  return (
    <svg {...common} aria-hidden="true">
      <path d="M4 2v8M8 2v8" />
    </svg>
  );
}

export function ClassBadge({
  value,
  small = false,
}: {
  value: AutomationClass | null | undefined;
  small?: boolean;
}) {
  if (!isClass(value)) {
    return (
      <span className={`bd n${small ? ' small' : ''}`} title="Not classified yet">
        NOT CLASSIFIED
      </span>
    );
  }
  return (
    <span className={`bd ${TONE[value]}${small ? ' small' : ''}`}>
      <Glyph kind={value} />
      {LABEL[value]}
    </span>
  );
}

export { LABEL as CLASS_LABEL, TONE as CLASS_TONE };
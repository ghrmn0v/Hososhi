/**
 * Display formatting.
 *
 * The single most important rule in this file: a metric that is `null` renders as the
 * text "not measured" — never as 0, never as a dash that could be read as a value, and
 * never as an invented number. There is no default and no fallback number.
 */

import type { SourceKind } from './types';

export const NOT_MEASURED = 'not measured';

/** Placeholder for a timestamp that was not recorded. Timestamps are not metrics. */
export const NO_TIME = '--:--';

/** Returns the value, or "not measured" when it is null/undefined. */
export function metric(value: number | null | undefined): string {
  return value === null || value === undefined ? NOT_MEASURED : String(value);
}

/** Processing time in ms → human readable. null → "not measured". */
export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return NOT_MEASURED;
  if (ms < 1000) return `${ms} ms`;
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds} s`;
  return `${minutes} min ${seconds} s`;
}

/** A ratio 0–1 → percentage. null → "not measured". */
export function percent(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return NOT_MEASURED;
  return `${Math.round(ratio * 100)}%`;
}

/** Confidence is reported as a 0–1 ratio from the API. */
export function confidence(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return NOT_MEASURED;
  return ratio.toFixed(2);
}

/** Signed delta; null → "not measured". */
export function delta(value: number | null | undefined, suffix = ''): string {
  if (value === null || value === undefined) return NOT_MEASURED;
  const sign = value > 0 ? '+' : '';
  return `${sign}${value}${suffix}`;
}

export function timestamp(iso: string | null | undefined): string {
  if (!iso) return NO_TIME;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return NO_TIME;
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function clockTime(iso: string | null | undefined): string {
  if (!iso) return NO_TIME;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return NO_TIME;
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

export function dateOnly(value: string | null | undefined): string {
  if (!value) return NO_TIME;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: '2-digit' });
}

/** Human wording for where a number came from. Shown next to every results block. */
export function sourceLabel(source: SourceKind | null | undefined): string {
  switch (source) {
    case 'replayed_from_dataset':
      return 'replayed from dataset';
    case 'measured_in_this_run':
      return 'measured in this run';
    case 'none':
    default:
      return 'not measured';
  }
}

/** "Do not call a method on a possibly-null value" guard for class rendering. */
export function isClass(value: string | null | undefined): value is
  | 'SAFE'
  | 'HUMAN_REVIEW'
  | 'HUMAN_REQUIRED' {
  return value === 'SAFE' || value === 'HUMAN_REVIEW' || value === 'HUMAN_REQUIRED';
}
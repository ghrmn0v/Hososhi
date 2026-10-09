'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/errors';

type State<T> =
  | { status: 'loading'; data: null; error: null }
  | { status: 'success'; data: T; error: null }
  | { status: 'error'; data: null; error: Error };

type Entry<T> = { key: string; state: State<T> };

const LOADING: State<never> = { status: 'loading', data: null, error: null } as State<never>;

/**
 * Loads one API resource with explicit loading / success / error state.
 * A blank screen is a defect, so callers must render all three.
 *
 * Staleness is derived from a key rather than by resetting state inside the effect,
 * which keeps the hook free of cascading renders on dependency change.
 */
export function useResource<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: unknown[],
): State<T> & { reload: () => void } {
  const key = deps.map((d) => String(d)).join('|');
  const [entry, setEntry] = useState<Entry<T>>({ key, state: LOADING });
  const [nonce, setNonce] = useState(0);
  const loaderRef = useRef(loader);

  // The loader closes over props; keep the latest one without reading the ref in render.
  useEffect(() => {
    loaderRef.current = loader;
  });

  useEffect(() => {
    const ac = new AbortController();
    let alive = true;
    const currentKey = `${key}|${nonce}`;

    loaderRef.current(ac.signal).then(
      (data) => {
        if (alive) setEntry({ key: currentKey, state: { status: 'success', data, error: null } });
      },
      (err: unknown) => {
        if (!alive) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setEntry({
          key: currentKey,
          state: {
            status: 'error',
            data: null,
            error:
              err instanceof ApiError || err instanceof Error
                ? err
                : new Error('Unknown error'),
          },
        });
      },
    );

    return () => {
      alive = false;
      ac.abort();
    };
  }, [key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const fresh = entry.key === `${key}|${nonce}`;
  return { ...(fresh ? entry.state : LOADING), reload } as State<T> & { reload: () => void };
}
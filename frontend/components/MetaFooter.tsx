'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Meta } from '@/lib/types';

/**
 * Transparency footer.
 *
 * Surfaces the dataset + model disclosure from GET /meta on screen, so a judge can
 * see where the numbers come from. When fixture mode is on that is stated here too —
 * a fixture-backed demo must never be shown without disclosure.
 */
export function MetaFooter() {
  const [meta, setMeta] = useState<Meta | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    api
      .meta(ac.signal)
      .then(setMeta)
      .catch(() => setMeta(null));
    return () => ac.abort();
  }, []);

  return (
    <footer className="foot">
      {api.isFixtureMode ? (
        <p style={{ marginBottom: 8 }}>
          <b>Fixture mode is on.</b> This page is rendered from local sample data — no
          backend was called and no measurement was taken. Run in live mode before the
          demo and disclose fixture use if it is ever left on.
        </p>
      ) : null}

      {meta ? (
        <p style={{ marginBottom: 8 }}>
          <b>Data.</b> {meta.dataset.synthetic ? 'Synthetic dataset' : 'Dataset'} —{' '}
          {meta.dataset.description ?? 'no description provided by the API'}.{' '}
          {meta.dataset.events ?? '—'} events. <b>Model.</b>{' '}
          {meta.ai.provider && meta.ai.model ? (
            <>
              <code>
                {meta.ai.provider}/{meta.ai.model}
              </code>
              {meta.ai.fallback_used ? ' (fallback provider was used)' : null}
            </>
          ) : (
            'not reported by the API'
          )}
          .
        </p>
      ) : null}

      <p>Hososhi — OBSERVE → UNDERSTAND → AUTOMATE → MEASURE.</p>
    </footer>
  );
}
import { Suspense } from 'react';
import { AutomationRun } from '@/components/screens/AutomationRun';
import { MetaFooter } from '@/components/MetaFooter';
import { LoadingCard } from '@/components/States';

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  return (
    <>
      <Suspense fallback={<LoadingCard label="LOADING · RUN" lines={4} />}>
        <Inner params={params} />
      </Suspense>
      <MetaFooter />
    </>
  );
}

async function Inner({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // No run id in the URL: the screen starts a run and rewrites the URL.
  return <AutomationRun workflowId={id} />;
}
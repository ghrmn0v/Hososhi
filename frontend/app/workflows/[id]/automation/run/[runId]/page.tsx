import { Suspense } from 'react';
import { AutomationRun } from '@/components/screens/AutomationRun';
import { MetaFooter } from '@/components/MetaFooter';
import { LoadingCard } from '@/components/States';

export default function Page({
  params,
}: {
  params: Promise<{ id: string; runId: string }>;
}) {
  return (
    <>
      <Suspense fallback={<LoadingCard label="LOADING · RUN" lines={4} />}>
        <Inner params={params} />
      </Suspense>
      <MetaFooter />
    </>
  );
}

async function Inner({ params }: { params: Promise<{ id: string; runId: string }> }) {
  const { id, runId } = await params;
  return <AutomationRun workflowId={id} runId={runId} />;
}
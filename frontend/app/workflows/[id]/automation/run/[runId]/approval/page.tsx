import { Suspense } from 'react';
import { HumanApproval } from '@/components/screens/HumanApproval';
import { MetaFooter } from '@/components/MetaFooter';
import { LoadingCard } from '@/components/States';

export default function Page({
  params,
}: {
  params: Promise<{ id: string; runId: string }>;
}) {
  return (
    <>
      <Suspense fallback={<LoadingCard label="LOADING · APPROVAL" lines={3} />}>
        <Inner params={params} />
      </Suspense>
      <MetaFooter />
    </>
  );
}

async function Inner({ params }: { params: Promise<{ id: string; runId: string }> }) {
  const { id, runId } = await params;
  return <HumanApproval workflowId={id} runId={runId} />;
}
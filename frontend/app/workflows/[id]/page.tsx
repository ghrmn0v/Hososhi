import { Suspense } from 'react';
import { WorkflowDetail } from '@/components/screens/WorkflowDetail';
import { MetaFooter } from '@/components/MetaFooter';
import { LoadingCard } from '@/components/States';

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  return (
    <>
      <Suspense fallback={<LoadingCard label="LOADING · WORKFLOW" lines={3} />}>
        <Inner params={params} />
      </Suspense>
      <MetaFooter />
    </>
  );
}

async function Inner({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <WorkflowDetail workflowId={id} />;
}
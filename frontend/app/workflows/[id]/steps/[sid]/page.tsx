import { Suspense } from 'react';
import { StepIntelligence } from '@/components/screens/StepIntelligence';
import { MetaFooter } from '@/components/MetaFooter';
import { LoadingCard } from '@/components/States';

export default function Page({
  params,
}: {
  params: Promise<{ id: string; sid: string }>;
}) {
  return (
    <>
      <Suspense fallback={<LoadingCard label="LOADING · STEP" lines={3} />}>
        <Inner params={params} />
      </Suspense>
      <MetaFooter />
    </>
  );
}

async function Inner({ params }: { params: Promise<{ id: string; sid: string }> }) {
  const { id, sid } = await params;
  return <StepIntelligence workflowId={id} stepId={sid} />;
}
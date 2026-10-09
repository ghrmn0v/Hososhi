import { Suspense } from 'react';
import { AutomationAnalysis } from '@/components/screens/AutomationAnalysis';
import { MetaFooter } from '@/components/MetaFooter';
import { LoadingCard } from '@/components/States';

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  return (
    <>
      <Suspense fallback={<LoadingCard label="LOADING · ANALYSIS" lines={4} />}>
        <Inner params={params} />
      </Suspense>
      <MetaFooter />
    </>
  );
}

async function Inner({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AutomationAnalysis workflowId={id} />;
}
import { Suspense } from 'react';
import { WorkflowList } from '@/components/screens/WorkflowList';
import { MetaFooter } from '@/components/MetaFooter';
import { LoadingCard } from '@/components/States';

export default function Page() {
  return (
    <>
      <Suspense fallback={<LoadingCard label="LOADING · WORKFLOWS" lines={3} />}>
        <WorkflowList />
      </Suspense>
      <MetaFooter />
    </>
  );
}
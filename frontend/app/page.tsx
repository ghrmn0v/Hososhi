import { Suspense } from 'react';
import { Dashboard } from '@/components/screens/Dashboard';
import { MetaFooter } from '@/components/MetaFooter';
import { LoadingCard } from '@/components/States';

export default function Page() {
  return (
    <>
      <Suspense fallback={<LoadingCard label="LOADING · OVERVIEW" lines={2} />}>
        <Dashboard />
      </Suspense>
      <MetaFooter />
    </>
  );
}
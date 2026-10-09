import { Suspense } from 'react';
import { Activity } from '@/components/screens/Activity';
import { MetaFooter } from '@/components/MetaFooter';
import { LoadingCard } from '@/components/States';

export default function Page() {
  return (
    <>
      <Suspense fallback={<LoadingCard label="LOADING · ACTIVITY" lines={4} />}>
        <Activity />
      </Suspense>
      <MetaFooter />
    </>
  );
}
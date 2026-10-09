import { Suspense } from 'react';
import { AutomationList } from '@/components/screens/AutomationList';
import { MetaFooter } from '@/components/MetaFooter';
import { LoadingCard } from '@/components/States';

export default function Page() {
  return (
    <>
      <Suspense fallback={<LoadingCard label="LOADING · AUTOMATION" lines={4} />}>
        <AutomationList />
      </Suspense>
      <MetaFooter />
    </>
  );
}
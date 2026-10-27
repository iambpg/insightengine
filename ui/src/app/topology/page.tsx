import React, { Suspense } from 'react';
import AppLayout from '@/components/AppLayout';
import TopologyView from '@/app/topology/components/TopologyView';

export default function TopologyPage() {
  return (
    <AppLayout>
      <Suspense fallback={null}>
        <TopologyView />
      </Suspense>
    </AppLayout>
  );
}

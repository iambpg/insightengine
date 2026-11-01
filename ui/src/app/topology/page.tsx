import React, { Suspense } from 'react';
import AppLayout from '@/components/AppLayout';
import TopologyView from '@/app/topology/components/TopologyView';

export default function TopologyPage() {
  return (
    <AppLayout>
      <Suspense fallback={<div role="status" className="px-4 py-6 text-sm text-muted-foreground">Loading topology</div>}>
        <TopologyView />
      </Suspense>
    </AppLayout>
  );
}

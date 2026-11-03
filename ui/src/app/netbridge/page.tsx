import React, { Suspense } from 'react';
import AppLayout from '@/components/AppLayout';
import NetBridgeView from '@/app/netbridge/components/NetBridgeView';

export default function NetBridgePage() {
  return (
    <AppLayout>
      <Suspense fallback={null}>
        <NetBridgeView />
      </Suspense>
    </AppLayout>
  );
}

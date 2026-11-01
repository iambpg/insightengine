import React, { Suspense } from 'react';
import AppLayout from '@/components/AppLayout';
import DeviceDetailView from '@/app/device-detail/components/DeviceDetailView';

function DeviceLoading() {
  return (
    <div role="status" className="px-4 py-6 text-sm text-muted-foreground">
      Loading device
    </div>
  );
}

export default function DeviceDetailPage() {
  return (
    <AppLayout>
      <Suspense fallback={<DeviceLoading />}>
        <DeviceDetailView />
      </Suspense>
    </AppLayout>
  );
}
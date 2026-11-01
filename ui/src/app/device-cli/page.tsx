import React, { Suspense } from 'react';
import AppLayout from '@/components/AppLayout';
import DeviceCliView from '@/app/device-cli/components/DeviceCliView';

function DeviceLoading() {
  return (
    <div role="status" className="px-4 py-6 text-sm text-muted-foreground">
      Loading device
    </div>
  );
}

export default function DeviceCliPage() {
  return (
    <AppLayout>
      <Suspense fallback={<DeviceLoading />}>
        <DeviceCliView />
      </Suspense>
    </AppLayout>
  );
}

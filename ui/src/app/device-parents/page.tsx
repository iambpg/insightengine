'use client';

import React, { Suspense } from 'react';
import AppLayout from '@/components/AppLayout';
import DeviceParentsView from '@/app/device-parents/components/DeviceParentsView';

export default function DeviceParentsPage() {
  return (
    <AppLayout>
      <Suspense fallback={<div role="status" className="px-4 py-6 text-sm text-muted-foreground">Loading device parents</div>}>
        <DeviceParentsView />
      </Suspense>
    </AppLayout>
  );
}

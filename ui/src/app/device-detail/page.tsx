import React from 'react';
import AppLayout from '@/components/AppLayout';
import DeviceDetailView from '@/app/device-detail/components/DeviceDetailView';

export default function DeviceDetailPage() {
  return (
    <AppLayout>
      <DeviceDetailView />
    </AppLayout>
  );
}
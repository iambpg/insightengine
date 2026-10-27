import React from 'react';
import AppLayout from '@/components/AppLayout';
import DeviceListView from '@/app/device-list/components/DeviceListView';

export default function DeviceListPage() {
  return (
    <AppLayout>
      <DeviceListView />
    </AppLayout>
  );
}
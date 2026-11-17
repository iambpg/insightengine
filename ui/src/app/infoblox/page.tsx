import React from 'react';
import AppLayout from '@/components/AppLayout';
import InfobloxDashboard from '@/app/infoblox/components/InfobloxDashboard';

export default function InfobloxPage() {
  return (
    <AppLayout>
      <InfobloxDashboard />
    </AppLayout>
  );
}

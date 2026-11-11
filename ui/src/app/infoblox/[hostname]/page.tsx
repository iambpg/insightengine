import React from 'react';
import AppLayout from '@/components/AppLayout';
import InfobloxMemberView from '@/app/infoblox/components/InfobloxMemberView';

export default async function InfobloxMemberPage({
  params,
}: {
  params: Promise<{ hostname: string }>;
}) {
  const { hostname } = await params;
  return (
    <AppLayout>
      <InfobloxMemberView hostname={hostname} />
    </AppLayout>
  );
}

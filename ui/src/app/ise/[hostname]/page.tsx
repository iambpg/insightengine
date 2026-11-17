import React from 'react';
import AppLayout from '@/components/AppLayout';
import IseNodeView from '@/app/ise/components/IseNodeView';

export default async function IseNodePage({
  params,
}: {
  params: Promise<{ hostname: string }>;
}) {
  const { hostname } = await params;
  return (
    <AppLayout>
      <IseNodeView hostname={hostname} />
    </AppLayout>
  );
}

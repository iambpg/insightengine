import React, { Suspense } from 'react';
import AppLayout from '@/components/AppLayout';
import NetBridgeView from '@/app/netbridge/components/NetBridgeView';

export default async function NetBridgePage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string | string[] }>;
}) {
  const params = await searchParams;
  const raw = params.tab;
  const tab = Array.isArray(raw) ? raw[0] : raw || 'dashboard';
  return (
    <AppLayout>
      <Suspense fallback={null}>
        <NetBridgeView initialTab={tab} />
      </Suspense>
    </AppLayout>
  );
}

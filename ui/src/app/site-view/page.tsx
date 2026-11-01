import React, { Suspense } from 'react';
import AppLayout from '@/components/AppLayout';
import SiteViewScreen from '@/app/site-view/components/SiteViewScreen';

function SiteLoading() {
  return (
    <div role="status" className="px-4 py-6 text-sm text-muted-foreground">
      Loading site
    </div>
  );
}

export default function SiteViewPage() {
  return (
    <AppLayout>
      <Suspense fallback={<SiteLoading />}>
        <SiteViewScreen />
      </Suspense>
    </AppLayout>
  );
}
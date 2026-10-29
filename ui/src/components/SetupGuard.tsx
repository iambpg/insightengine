'use client';

import { useEffect } from 'react';
import { api } from '@/lib/apiClient';
import { reportLoadError } from '@/lib/loadError';
import { redirectForSetup } from '@/lib/setupRedirect';

// Sends the browser to the separately served setup app unless setup is complete.
// A failed request does not redirect: that would loop if the setup service is down.
export default function SetupGuard() {
  useEffect(() => {
    let cancelled = false;
    api
      .getSetupState()
      .then((state) => {
        if (cancelled) return;
        const target = redirectForSetup(state, window.location.pathname);
        if (target) window.location.assign(target);
      })
      .catch((cause) => {
        reportLoadError(cause, 'setup');
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return null;
}

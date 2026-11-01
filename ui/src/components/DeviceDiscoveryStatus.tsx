'use client';

import React, { useEffect, useRef, useState } from 'react';
import Badge from '@/components/ui/Badge';
import { api } from '@/lib/apiClient';
import type { DeviceDiscoveryJob, DeviceJobStatus } from '@/lib/contract';

const TONE: Record<DeviceJobStatus, 'success' | 'info' | 'destructive'> = {
  queued: 'info',
  running: 'info',
  done: 'success',
  error: 'destructive',
};

export function DeviceDiscoveryStatus({ job }: { job: DeviceDiscoveryJob | null }) {
  if (!job) return null;
  return (
    <div className="mt-3 rounded-md border border-border p-3" aria-label="Discovery status">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={TONE[job.status]}>{job.status}</Badge>
        <span className="font-mono-data text-xs">{job.ip}</span>
        {job.message ? <span className="text-xs text-muted-foreground">{job.message}</span> : null}
      </div>
      <ol className="mt-2 flex flex-col gap-1" aria-label="Discovery steps">
        {job.steps.map((step, index) => (
          <li key={`${step.name}-${step.ip ?? index}`} className="flex flex-wrap items-center gap-2 text-xs">
            <Badge tone={TONE[step.status]}>{step.status}</Badge>
            <span className="font-medium">{step.name}</span>
            {step.message ? <span className="text-muted-foreground">{step.message}</span> : null}
          </li>
        ))}
      </ol>
    </div>
  );
}

export function usePolledDeviceDiscovery(
  initial: DeviceDiscoveryJob | null,
  handlers?: {
    onDone?: (job: DeviceDiscoveryJob) => void;
    onError?: (job: DeviceDiscoveryJob) => void;
  }
): DeviceDiscoveryJob | null {
  const [job, setJob] = useState<DeviceDiscoveryJob | null>(initial);
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;
  const reported = useRef<string | null>(null);

  useEffect(() => {
    setJob(initial);
  }, [initial]);

  const jobId = job?.id;
  const jobStatus = job?.status;

  useEffect(() => {
    if (!jobId || !jobStatus) return undefined;
    if (jobStatus === 'done' || jobStatus === 'error') {
      const key = `${jobStatus}:${jobId}`;
      if (reported.current !== key) {
        reported.current = key;
        const current = job;
        if (current) {
          if (jobStatus === 'done') handlersRef.current?.onDone?.(current);
          else handlersRef.current?.onError?.(current);
        }
      }
      return undefined;
    }
    let cancelled = false;
    const tick = () => {
      api
        .getDeviceDiscovery(jobId)
        .then((next) => {
          if (!cancelled) setJob(next);
        })
        .catch(() => undefined);
    };
    tick();
    const timer = window.setInterval(tick, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
    // Poll on id/status only. Depending on the job object would refetch in a loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, jobStatus]);

  return job;
}

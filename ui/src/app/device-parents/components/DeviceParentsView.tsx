'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { api } from '@/lib/apiClient';
import { devicePath } from '@/lib/apiMode';
import { reportLoadError } from '@/lib/loadError';
import type { HierarchyNode, HierarchyReport } from '@/lib/types';

type Result = { id: string; ok: boolean; error?: string; hostname?: string };

export default function DeviceParentsView() {
  const [report, setReport] = useState<HierarchyReport | null>(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [override, setOverride] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [autoApply, setAutoApply] = useState(false);

  const load = useCallback(() => {
    setError('');
    api
      .getHierarchy()
      .then((body) => {
        setReport(body);
        setAutoApply(Boolean(body.autoApply));
      })
      .catch((cause) => setError(reportLoadError(cause, 'device parents')));
  }, []);

  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => {
    return (report?.nodes ?? []).filter((node) => !node.root || node.differs || node.flagged);
  }, [report]);

  const choices = report?.nodes ?? [];
  const ticked = rows.filter((row) => selected[row.id]);

  const approve = async (items: { id: string; parentId?: string; parentInterface?: string; uplinkInterface?: string }[]) => {
    if (!items.length) return;
    setBusy(true);
    try {
      const body = await api.approveHierarchy({ items });
      const failed = (body.results ?? []).filter((row: Result) => !row.ok);
      if (failed.length) toast.error(failed.map((row) => `${row.hostname || row.id}: ${row.error || 'not written'}`).join('; '));
      else toast.success(`Wrote ${body.results?.length || items.length} parent${items.length === 1 ? '' : 's'} to NetBox`);
      setSelected({});
      load();
    } catch (cause) {
      toast.error(reportLoadError(cause, 'the NetBox write'));
    } finally {
      setBusy(false);
    }
  };

  const itemFor = (node: HierarchyNode) => {
    const chosen = override[node.id];
    if (chosen === '') return { id: node.id, parentId: '', parentInterface: '', uplinkInterface: '' };
    if (chosen) return { id: node.id, parentId: chosen, parentInterface: node.parentInterface, uplinkInterface: node.uplinkInterface };
    return { id: node.id };
  };

  const saveAuto = async (next: boolean) => {
    if (next) {
      const agreed = window.confirm('Auto-apply writes every proposed parent to NetBox the next time this page loads. Leave it off to approve each row yourself.');
      if (!agreed) return;
    }
    setBusy(true);
    try {
      const saved = await api.saveHierarchySettings(next);
      setAutoApply(saved.autoApply);
      toast.success(saved.autoApply ? 'Auto-apply is on' : 'Auto-apply is off');
    } catch (cause) {
      toast.error(reportLoadError(cause, 'the auto-apply setting'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3 px-3 sm:px-4">
      <header className="rounded-none border-x-0 border-y border-border bg-card p-4 shadow-card">
        <h1 className="text-xl font-semibold tracking-tight">Device parents</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Proposed from CDP and LLDP. Nothing is written to NetBox until you approve it. Auto-apply is off unless you turn it on.
        </p>
        <label className="mt-3 inline-flex items-center gap-2 text-sm">
          <input type="checkbox" checked={autoApply} disabled={busy} onChange={(event) => saveAuto(event.target.checked)} />
          Auto-apply proposed parents
        </label>
      </header>

      {error ? <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{error}</p> : null}
      {report?.degraded?.length ? (
        <p className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Some sources did not answer: {report.degraded.join(', ')}. The tree may be incomplete.
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={busy || ticked.length === 0}
          onClick={() => approve(ticked.map(itemFor))}
          className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          Approve selected ({ticked.length})
        </button>
        <button
          type="button"
          disabled={busy || rows.length === 0}
          onClick={() => {
            if (!window.confirm('Write every proposed parent to NetBox?')) return;
            approve(rows.filter((row) => row.differs || override[row.id] !== undefined).map(itemFor));
          }}
          className="rounded-md border border-border bg-card px-3 py-2 text-sm font-medium disabled:opacity-50"
        >
          Approve all proposals
        </button>
      </div>

      <div className="overflow-x-auto rounded-none border-x-0 border-y border-border bg-card shadow-card">
        <table className="w-full min-w-[880px] text-left text-sm">
          <thead className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2"> </th>
              <th className="px-3 py-2">Device</th>
              <th className="px-3 py-2">Proposed parent</th>
              <th className="px-3 py-2">Ports</th>
              <th className="px-3 py-2">Override</th>
            </tr>
          </thead>
          <tbody>
            {report == null ? (
              <tr><td colSpan={5} className="px-3 py-6 text-muted-foreground">Loading…</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={5} className="px-3 py-6 text-muted-foreground">No monitored devices need a parent.</td></tr>
            ) : rows.map((node) => (
              <tr key={node.id} className="border-t border-border">
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label={`Select ${node.hostname}`}
                    checked={Boolean(selected[node.id])}
                    onChange={(event) => setSelected((current) => ({ ...current, [node.id]: event.target.checked }))}
                  />
                </td>
                <td className="px-3 py-2">
                  <Link href={devicePath(node.id, node.formFactor || 'generic')} className="font-mono-data text-primary hover:underline">{node.hostname}</Link>
                  {node.flagged ? <p className="text-xs text-amber-800">No path to a subnet root.</p> : null}
                  {node.wlc ? <p className="text-xs text-muted-foreground">Joined WLC {node.wlc}</p> : null}
                </td>
                <td className="px-3 py-2 font-mono-data">
                  {node.parentHostname || '—'}
                </td>
                <td className="px-3 py-2 font-mono-data text-muted-foreground">
                  {node.parentHostname ? `${node.uplinkInterface} → ${node.parentHostname} ${node.parentInterface}` : '—'}
                </td>
                <td className="px-3 py-2">
                  <select
                    aria-label={`Parent override for ${node.hostname}`}
                    className="w-full rounded-md border border-border bg-background px-2 py-1 text-sm"
                    value={override[node.id] ?? node.parentId}
                    onChange={(event) => setOverride((current) => ({ ...current, [node.id]: event.target.value }))}
                  >
                    <option value="">No parent</option>
                    {choices.filter((choice) => choice.id !== node.id).map((choice) => (
                      <option key={choice.id} value={choice.id}>{choice.hostname}</option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

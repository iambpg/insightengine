'use client';

import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import Pagination from '@/components/ui/Pagination';
import Modal from '@/components/ui/Modal';
import { api } from '@/lib/apiClient';
import { isApiError } from '@/lib/apiError';
import NotInNetBoxView from '@/app/not-in-net-box/components/NotInNetBoxView';
import { allowOperate } from '@/lib/settings/access';
import { useKnownRole } from '@/lib/useSession';

const TABS = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'missing', label: 'Not in NetBox' },
  { id: 'stacks', label: 'Stacks' },
  { id: 'addresses', label: 'IP Addresses' },
  { id: 'access-points', label: 'Access Points' },
  { id: 'controllers', label: 'Wireless Controllers' },
  { id: 'fortimanager', label: 'FortiManager' },
  { id: 'sites', label: 'Sites' },
  { id: 'conflicts', label: 'Conflicts & Queue' },
  { id: 'history', label: 'Sync History' },
  { id: 'eox', label: 'End of Life' },
] as const;

type TabId = (typeof TABS)[number]['id'];

const LIST_TABS = new Set(['stacks', 'addresses', 'controllers', 'fortimanager', 'sites', 'conflicts', 'history', 'access-points', 'eox']);

function readTab(initial: string): TabId {
  const known = TABS.some((tab) => tab.id === initial);
  return (known ? initial : 'dashboard') as TabId;
}

export default function NetBridgeView({ initialTab = 'dashboard' }: { initialTab?: string }) {
  const canWrite = allowOperate(useKnownRole());
  const [tab, setTab] = useState<TabId>(readTab(initialTab));
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [open, setOpen] = useState(0);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search).get('tab');
    if (query && TABS.some((item) => item.id === query)) setTab(query as TabId);
  }, []);

  const choose = (next: TabId) => {
    setTab(next);
    const url = new URL(window.location.href);
    url.searchParams.set('tab', next);
    window.history.replaceState(null, '', url.pathname + url.search);
  };

  const loadSummary = () => {
    api
      .netbridgeGet('/summary')
      .then((body) => setSummary(body as Record<string, unknown>))
      .catch(() => setSummary(null));
    api
      .netbridgeGet('/open-count')
      .then((body) => setOpen(Number((body as { open?: number }).open || 0)))
      .catch(() => setOpen(0));
  };

  useEffect(() => {
    loadSummary();
  }, [tab]);

  return (
    <div className="space-y-4">
      <header className="px-4">
        <h1 className="text-2xl font-semibold tracking-tight">NetBridge</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Copy what Netdisco, the controllers, and FortiManager already know into NetBox. Nothing is
          deleted, existing names stay, and site, role, and rack are not overwritten. Every write is a
          dry run until you confirm it.
        </p>
      </header>
      <div role="tablist" aria-label="NetBridge" className="flex gap-1 overflow-x-auto px-4">
        {TABS.map((item) => {
          const on = tab === item.id;
          const badge = item.id === 'conflicts' ? open : 0;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={on}
              onClick={() => choose(item.id)}
              className={`shrink-0 rounded-md px-3 py-1.5 text-sm ${on ? 'bg-navy font-semibold text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}`}
            >
              {item.label}
              {badge ? <span className="ml-1 rounded-full bg-warning px-1.5 text-[10px] font-bold text-warning-foreground">{badge}</span> : null}
            </button>
          );
        })}
      </div>
      <div role="tabpanel">
        {tab === 'dashboard' && <Dashboard summary={summary} onOpen={choose} onRefresh={loadSummary} />}
        {tab === 'missing' && <NotInNetBoxView embedded />}
        {tab === 'access-points' && <AccessPoints canWrite={canWrite} />}
        {tab === 'eox' && <EoxTab canWrite={canWrite} />}
        {LIST_TABS.has(tab) && tab !== 'access-points' && tab !== 'eox' ? <ResourceTab kind={tab} canWrite={canWrite} /> : null}
      </div>
    </div>
  );
}

function Dashboard({
  summary,
  onOpen,
  onRefresh,
}: {
  summary: Record<string, unknown> | null;
  onOpen: (tab: TabId) => void;
  onRefresh: () => void;
}) {
  const cards: { label: string; key: string; tab: TabId }[] = [
    { label: 'Netdisco devices', key: 'netdiscoDevices', tab: 'stacks' },
    { label: 'NetBox devices', key: 'netboxDevices', tab: 'addresses' },
    { label: 'Not in NetBox', key: 'notInNetbox', tab: 'missing' },
    { label: 'Stacks pending', key: 'stacksPending', tab: 'stacks' },
    { label: 'APs pending', key: 'apsPending', tab: 'access-points' },
    { label: 'Open conflicts', key: 'openConflicts', tab: 'conflicts' },
  ];
  const jobs = (summary?.jobs as Array<Record<string, unknown>> | undefined) ?? [];
  const eox = (summary?.eox as { message?: string; configured?: boolean } | undefined) ?? {};
  const fmg = (summary?.fortimanager as { message?: string } | undefined) ?? {};
  return (
    <div className="space-y-4 px-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((card) => (
          <button
            key={card.key}
            type="button"
            onClick={() => onOpen(card.tab)}
            className="rounded-md border border-border bg-card p-4 text-left shadow-card"
          >
            <p className="text-xs uppercase tracking-wide text-muted-foreground">{card.label}</p>
            <p className="mt-1 text-2xl font-semibold tabular">{summary ? String(summary[card.key] ?? '—') : '—'}</p>
          </button>
        ))}
      </div>
      {eox.message ? <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">{eox.message}</p> : null}
      {fmg.message ? <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">{fmg.message}</p> : null}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => onOpen('missing')} className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground">Review devices</button>
        <button type="button" onClick={() => onOpen('access-points')} className="rounded-md border border-border px-3 py-1.5 text-sm">Scan access points</button>
        <button type="button" onClick={() => onOpen('eox')} className="rounded-md border border-border px-3 py-1.5 text-sm">End of life</button>
        <button type="button" onClick={onRefresh} className="rounded-md border border-border px-3 py-1.5 text-sm">Refresh counts</button>
      </div>
      <section aria-label="Recent jobs" className="rounded-md border border-border">
        <h2 className="border-b border-border px-3 py-2 text-sm font-semibold">Last sync jobs</h2>
        {jobs.length === 0 ? <p className="px-3 py-4 text-sm text-muted-foreground">No sync jobs yet.</p> : (
          <ul className="divide-y divide-border text-sm">
            {jobs.map((job) => (
              <li key={String(job.id)} className="flex flex-wrap gap-3 px-3 py-2">
                <span className="font-medium">{String(job.kind)}</span>
                <span className="text-muted-foreground">{String(job.actor || '')}</span>
                <span>{String(job.status)}</span>
                <span className="font-mono-data text-xs text-muted-foreground">{String(job.startedAt || '')}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function ResourceTab({ kind, canWrite }: { kind: string; canWrite: boolean }) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [q, setQ] = useState('');
  const [data, setData] = useState<{ rows: Record<string, unknown>[]; total: number; message?: string; instances?: { name: string; devices: number }[] } | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const writable = kind === 'stacks' || kind === 'addresses' || kind === 'controllers' || kind === 'sites';

  const load = () => {
    const status = kind === 'conflicts' ? '&status=open' : '';
    api
      .netbridgeGet(`/${kind}?page=${page}&page_size=${pageSize}&q=${encodeURIComponent(q)}${status}`)
      .then((body) => setData(body as { rows: Record<string, unknown>[]; total: number }))
      .catch((cause) => toast.error(isApiError(cause) ? cause.message : 'The list could not be loaded.'));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, page, pageSize, q]);

  const runPreview = async () => {
    setBusy(true);
    try {
      const body = (await api.netbridgePost(`/${kind}/preview`, {})) as Record<string, unknown>;
      setPreview(body);
    } catch (cause) {
      toast.error(isApiError(cause) ? cause.message : 'The preview failed. Nothing was written.');
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!preview?.previewId) return;
    setBusy(true);
    try {
      const result = (await api.netbridgePost(`/${kind}/apply`, { previewId: preview.previewId, confirm: true })) as { errors?: string[] };
      setPreview(null);
      toast.success(result.errors?.length ? 'Applied with errors. See Sync History.' : 'NetBox was updated.');
      load();
    } catch (cause) {
      toast.error(isApiError(cause) ? cause.message : 'NetBox was not changed.');
    } finally {
      setBusy(false);
    }
  };

  const resolve = async (id: number, action: 'resolve' | 'ignore') => {
    try {
      await api.netbridgePost(`/conflicts/${id}`, { action });
      load();
    } catch (cause) {
      toast.error(isApiError(cause) ? cause.message : 'The conflict was not updated.');
    }
  };

  const rows = data?.rows ?? [];
  const columns = rows[0] ? Object.keys(rows[0]).filter((key) => key !== 'members' && key !== 'detail').slice(0, 8) : [];
  return (
    <section className="mx-4 rounded-md border border-border bg-card" aria-label={kind}>
      <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
        <input
          aria-label={`Search ${kind}`}
          value={q}
          onChange={(event) => {
            setQ(event.target.value);
            setPage(1);
          }}
          placeholder="Search"
          className="h-9 min-w-[180px] flex-1 rounded-md border border-input px-3 text-sm"
        />
        {writable && canWrite ? (
          <button type="button" onClick={runPreview} disabled={busy} className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground">
            Preview
          </button>
        ) : null}
      </div>
      {data?.message ? <p className="px-3 py-2 text-sm text-muted-foreground">{data.message}</p> : null}
      {data?.instances?.length ? (
        <ul className="px-3 py-2 text-sm">
          {data.instances.map((instance) => (
            <li key={instance.name}>{instance.name}: {instance.devices} managed FortiGates</li>
          ))}
        </ul>
      ) : null}
      <div className="scroll-thin overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase text-muted-foreground">
              {columns.map((column) => <th key={column} className="px-3 py-2">{column}</th>)}
              {kind === 'conflicts' && canWrite ? <th className="px-3 py-2">Queue</th> : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={String(row.id ?? index)} className="border-b border-border">
                {columns.map((column) => (
                  <td key={column} className="px-3 py-2 align-top">{formatCell(row[column])}</td>
                ))}
                {kind === 'conflicts' && canWrite ? (
                  <td className="px-3 py-2">
                    <button type="button" className="mr-2 text-xs font-semibold" onClick={() => resolve(Number(row.id), 'resolve')}>Resolve</button>
                    <button type="button" className="text-xs" onClick={() => resolve(Number(row.id), 'ignore')}>Ignore</button>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination page={page} pageSize={pageSize} total={data?.total ?? 0} noun="rows" onPage={setPage} onPageSize={(size) => { setPageSize(size); setPage(1); }} />
      <Modal open={!!preview} onClose={() => !busy && setPreview(null)} title="Dry run" description={String(preview?.message || 'Confirm to write these changes to NetBox.')} footer={
        <>
          <button type="button" onClick={() => setPreview(null)} className="rounded-md border border-border px-3 py-1.5 text-sm">Cancel</button>
          <button type="button" disabled={busy} onClick={apply} className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground">Confirm write</button>
        </>
      }>
        <p className="text-sm">{String(preview?.changes ?? 0)} changes. Nothing has been written yet.</p>
      </Modal>
    </section>
  );
}

function AccessPoints({ canWrite }: { canWrite: boolean }) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [q, setQ] = useState('');
  const [model, setModel] = useState('');
  const [selected, setSelected] = useState<number[]>([]);
  const [data, setData] = useState<{ rows: Record<string, unknown>[]; total: number; models?: { model: string; count: number }[] } | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    api.netbridgeGet(`/access-points?page=${page}&page_size=${pageSize}&q=${encodeURIComponent(q)}&model=${encodeURIComponent(model)}`)
      .then((body) => setData(body as { rows: Record<string, unknown>[]; total: number; models?: { model: string; count: number }[] }))
      .catch((cause) => toast.error(isApiError(cause) ? cause.message : 'Access points could not be loaded.'));
  };
  useEffect(() => { load(); }, [page, pageSize, q, model]);

  const scan = async () => {
    setBusy(true);
    try {
      const result = (await api.netbridgePost('/access-points/scan', {})) as { message?: string };
      toast.success(result.message || 'Scan finished.');
      load();
    } catch (cause) {
      toast.error(isApiError(cause) ? cause.message : 'The scan failed.');
    } finally {
      setBusy(false);
    }
  };

  const ask = async () => {
    setBusy(true);
    try {
      setPreview((await api.netbridgePost('/access-points/preview', { ids: selected })) as Record<string, unknown>);
    } catch (cause) {
      toast.error(isApiError(cause) ? cause.message : 'Preview failed. Nothing was written.');
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    setBusy(true);
    try {
      await api.netbridgePost('/access-points/apply', { previewId: preview?.previewId, confirm: true });
      setPreview(null);
      setSelected([]);
      toast.success('Selected access points were sent to NetBox.');
      load();
    } catch (cause) {
      toast.error(isApiError(cause) ? cause.message : 'NetBox was not changed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mx-4 rounded-md border border-border bg-card" aria-label="Access points">
      <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
        <input aria-label="Search access points" value={q} onChange={(event) => { setQ(event.target.value); setPage(1); }} placeholder="Name, serial, IP, switch" className="h-9 min-w-[180px] flex-1 rounded-md border border-input px-3 text-sm" />
        {canWrite ? <button type="button" onClick={scan} disabled={busy} className="rounded-md border border-border px-3 py-1.5 text-sm">Scan controllers</button> : null}
        {canWrite ? <button type="button" onClick={ask} disabled={busy || selected.length === 0} className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground">Upload selected</button> : null}
      </div>
      <div className="flex flex-wrap gap-2 px-3 py-2">
        <FilterButton label="All models" on={model === ''} onClick={() => { setModel(''); setPage(1); }} />
        {(data?.models ?? []).map((item) => (
          <FilterButton key={item.model} label={`${item.model} (${item.count})`} on={model === item.model} onClick={() => { setModel(item.model); setPage(1); }} />
        ))}
      </div>
      <div className="scroll-thin overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase text-muted-foreground">
              <th className="px-3 py-2" />
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Model</th>
              <th className="px-3 py-2">Serial</th>
              <th className="px-3 py-2">IP</th>
              <th className="px-3 py-2">CDP neighbour</th>
            </tr>
          </thead>
          <tbody>
            {(data?.rows ?? []).map((row) => {
              const id = Number(row.id);
              const on = selected.includes(id);
              return (
                <tr key={id} className="border-b border-border">
                  <td className="px-3 py-2">
                    <input type="checkbox" aria-label={`Select ${row.name}`} checked={on} onChange={() => setSelected(on ? selected.filter((item) => item !== id) : [...selected, id])} />
                  </td>
                  <td className="px-3 py-2">{String(row.name || '')}</td>
                  <td className="px-3 py-2">{String(row.model || '')}</td>
                  <td className="px-3 py-2 font-mono-data text-xs">{String(row.serial || '')}</td>
                  <td className="px-3 py-2 font-mono-data text-xs">{String(row.ip || '')}</td>
                  <td className="px-3 py-2">{[row.neighbor, row.neighborPort].filter(Boolean).join(' ')}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <Pagination page={page} pageSize={pageSize} total={data?.total ?? 0} noun="access points" onPage={setPage} onPageSize={(size) => { setPageSize(size); setPage(1); }} />
      <Modal open={!!preview} onClose={() => !busy && setPreview(null)} title="Upload access points" description="NetBox devices are created for access points that are not already there. Existing devices are left as they are." footer={
        <>
          <button type="button" onClick={() => setPreview(null)} className="rounded-md border border-border px-3 py-1.5 text-sm">Cancel</button>
          <button type="button" disabled={busy} onClick={apply} className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground">Confirm upload</button>
        </>
      }>
        <p className="text-sm">{String(preview?.changes ?? 0)} devices will be created.</p>
      </Modal>
    </section>
  );
}

function EoxTab({ canWrite }: { canWrite: boolean }) {
  const [bucket, setBucket] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [q, setQ] = useState('');
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    api.netbridgeGet(`/eox?page=${page}&page_size=${pageSize}&q=${encodeURIComponent(q)}&bucket=${encodeURIComponent(bucket)}`)
      .then((body) => setData(body as Record<string, unknown>))
      .catch((cause) => toast.error(isApiError(cause) ? cause.message : 'EoX could not be loaded.'));
  };
  useEffect(() => { load(); }, [page, pageSize, q, bucket]);

  const refresh = async () => {
    setBusy(true);
    try {
      const result = (await api.netbridgePost('/eox/refresh', {})) as { message?: string; ok?: boolean };
      toast.success(result.message || 'Refresh finished.');
      load();
    } catch (cause) {
      toast.error(isApiError(cause) ? cause.message : 'EoX refresh failed.');
    } finally {
      setBusy(false);
    }
  };

  const counts = (data?.counts as Record<string, number> | undefined) ?? {};
  const rows = (data?.rows as Record<string, unknown>[] | undefined) ?? [];
  return (
    <section className="mx-4 space-y-3" aria-label="End of life">
      {data?.message ? <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">{String(data.message)}</p> : null}
      <div className="flex flex-wrap items-center gap-2">
        <FilterButton label={`Past LDoS (${counts.past ?? 0})`} on={bucket === 'past'} onClick={() => { setBucket('past'); setPage(1); }} />
        <FilterButton label={`<12 months (${counts.soon ?? 0})`} on={bucket === 'soon'} onClick={() => { setBucket('soon'); setPage(1); }} />
        <FilterButton label={`OK (${counts.ok ?? 0})`} on={bucket === 'ok'} onClick={() => { setBucket('ok'); setPage(1); }} />
        <FilterButton label={`Unknown (${counts.unknown ?? 0})`} on={bucket === 'unknown'} onClick={() => { setBucket('unknown'); setPage(1); }} />
        <FilterButton label="All" on={bucket === ''} onClick={() => { setBucket(''); setPage(1); }} />
        {canWrite ? <button type="button" onClick={refresh} disabled={busy} className="rounded-md border border-border px-3 py-1.5 text-sm">Refresh from Cisco</button> : null}
        {canWrite ? <button type="button" onClick={async () => {
          try { setPreview((await api.netbridgePost('/eox/preview', {})) as Record<string, unknown>); }
          catch (cause) { toast.error(isApiError(cause) ? cause.message : 'Preview failed.'); }
        }} className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground">Preview NetBox fields</button> : null}
      </div>
      <input aria-label="Search end of life" value={q} onChange={(event) => { setQ(event.target.value); setPage(1); }} placeholder="Name, PID, serial" className="h-9 w-full max-w-sm rounded-md border border-input px-3 text-sm" />
      <div className="scroll-thin overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase text-muted-foreground">
              {['Name', 'PID', 'Serial', 'End of sale', 'End of SW maintenance', 'End of security', 'Last date of support', 'Migration PID'].map((label) => <th key={label} className="px-3 py-2">{label}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={String(row.id)} className="border-b border-border">
                <td className="px-3 py-2">{String(row.name || '')}</td>
                <td className="px-3 py-2">{String(row.pid || '')}</td>
                <td className="px-3 py-2 font-mono-data text-xs">{String(row.serial || '')}</td>
                <td className="px-3 py-2">{String(row.end_of_sale || '—')}</td>
                <td className="px-3 py-2">{String(row.end_of_sw_maintenance || '—')}</td>
                <td className="px-3 py-2">{String(row.end_of_security || '—')}</td>
                <td className="px-3 py-2">{String(row.last_date_of_support || '—')}</td>
                <td className="px-3 py-2">{String(row.migration_pid || '—')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination page={page} pageSize={pageSize} total={Number(data?.total || 0)} noun="devices" onPage={setPage} onPageSize={(size) => { setPageSize(size); setPage(1); }} />
      <Modal open={!!preview} onClose={() => setPreview(null)} title="Write EoX dates" description="Only the EoX custom fields are updated, and only after you confirm." footer={
        <>
          <button type="button" onClick={() => setPreview(null)} className="rounded-md border border-border px-3 py-1.5 text-sm">Cancel</button>
          <button type="button" onClick={async () => {
            try {
              await api.netbridgePost('/eox/apply', { previewId: preview?.previewId, confirm: true });
              setPreview(null);
              toast.success('EoX custom fields were updated.');
            } catch (cause) {
              toast.error(isApiError(cause) ? cause.message : 'NetBox was not changed.');
            }
          }} className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground">Confirm write</button>
        </>
      }>
        <p className="text-sm">{String(preview?.changes ?? 0)} field updates.</p>
      </Modal>
    </section>
  );
}

function FilterButton({ label, on, onClick }: { label: string; on: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className={`rounded-full border px-3 py-1 text-xs font-semibold ${on ? 'border-navy bg-navy text-primary-foreground' : 'border-border'}`}>
      {label}
    </button>
  );
}

function formatCell(value: unknown): string {
  if (value == null) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

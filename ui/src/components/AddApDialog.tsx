'use client';

import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import Modal from '@/components/ui/Modal';
import { api } from '@/lib/apiClient';
import { isApiError } from '@/lib/apiError';
import type { DiscoveryCatalog } from '@/lib/contract';

export interface ApDraft {
  name: string;
  wlc?: string;
  model?: string;
  serial?: string;
  ip?: string;
  ios?: string;
  location?: string;
  siteTag?: string;
  suggestedSite?: string;
}

const EMPTY: DiscoveryCatalog = { roles: [], sites: [], platforms: [] };

function defaultRole(catalog: DiscoveryCatalog): string {
  const choices = catalog.roleChoices ?? [];
  const hit = choices.find((choice) => choice.slug === 'access-point' || choice.name.toLowerCase() === 'access point' || choice.name.toLowerCase() === 'access-point');
  if (hit) return hit.name;
  const named = catalog.roles.find((role) => role.toLowerCase() === 'access point' || role.toLowerCase() === 'access-point');
  return named || 'access-point';
}

function defaultSite(aps: ApDraft[], sites: string[]): string {
  const suggested = aps.map((ap) => (ap.suggestedSite || ap.siteTag || ap.location || '').trim()).filter(Boolean);
  const unique = Array.from(new Set(suggested));
  if (unique.length === 1) return unique[0];
  return suggested[0] || sites[0] || '';
}

export default function AddApDialog({
  open,
  aps,
  onClose,
  onDone,
}: {
  open: boolean;
  aps: ApDraft[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [catalog, setCatalog] = useState<DiscoveryCatalog>(EMPTY);
  const [role, setRole] = useState('access-point');
  const [site, setSite] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api.discoveryCatalog().then((data) => {
      if (cancelled) return;
      const next = { roles: data.roles ?? [], roleChoices: data.roleChoices, sites: data.sites ?? [], platforms: data.platforms ?? [] };
      setCatalog(next);
      setRole(defaultRole(next));
      setSite(defaultSite(aps, next.sites));
    }).catch(() => {
      if (!cancelled) {
        setCatalog(EMPTY);
        setRole('access-point');
        setSite(defaultSite(aps, []));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [open, aps]);

  const roles = (catalog.roleChoices?.map((choice) => choice.name).filter(Boolean) ?? catalog.roles);
  const roleOptions = roles.includes(role) || !role ? roles : [role, ...roles];
  const siteOptions = catalog.sites.includes(site) || !site ? catalog.sites : [site, ...catalog.sites];

  const submit = async () => {
    if (!role.trim() || !site.trim()) {
      toast.error('Role and site are required to create the access point in NetBox.');
      return;
    }
    setBusy(true);
    try {
      const result = await api.approveAccessPoints({
        role: role.trim(),
        site: site.trim(),
        accessPoints: aps.map((ap) => ({
          name: ap.name,
          wlc: ap.wlc || '',
          model: ap.model || '',
          serial: ap.serial || '',
          ip: ap.ip || '',
          ios: ap.ios || '',
          location: ap.location || '',
          siteTag: ap.siteTag || '',
        })),
      });
      const created = result.results.filter((row) => row.status === 'created').length;
      const skipped = result.results.filter((row) => row.status === 'skipped').length;
      const failed = result.results.filter((row) => row.status === 'failed').length;
      toast.success(`${created} added, ${skipped} already in NetBox, ${failed} failed.`);
      onDone();
      onClose();
    } catch (cause) {
      toast.error(isApiError(cause) ? cause.message : 'NetBox was not changed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={() => !busy && onClose()}
      title="Add to NetBox"
      description="Creates the access point in NetBox. A matching serial, or the same name, is left as it is."
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy} className="rounded-md border border-border px-3 py-1.5 text-sm">Cancel</button>
          <button type="button" onClick={submit} disabled={busy || aps.length === 0} className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground">Add {aps.length === 1 ? 'access point' : `${aps.length} access points`}</button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <p>{aps.length === 1 ? aps[0]?.name : `${aps.length} access points`}</p>
        <label className="block">
          <span className="text-xs font-medium text-muted-foreground">Role</span>
          <select aria-label="Role" value={role} onChange={(event) => setRole(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-input bg-card px-2">
            {roleOptions.map((item) => <option key={item} value={item}>{item}</option>)}
            {roleOptions.length === 0 ? <option value="access-point">access-point</option> : null}
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-medium text-muted-foreground">Site</span>
          <select aria-label="Site" value={site} onChange={(event) => setSite(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-input bg-card px-2">
            <option value="">Choose a site</option>
            {siteOptions.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
      </div>
    </Modal>
  );
}

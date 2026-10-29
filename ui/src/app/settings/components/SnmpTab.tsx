'use client';

import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import Badge from '@/components/ui/Badge';
import Icon from '@/components/ui/AppIcon';
import { isMockMode } from '@/lib/apiMode';
import { request } from '@/lib/http';

type Profile = {
  name?: string;
  auth?: string;
  source?: string;
  version?: string;
  port?: number;
  security_name?: string;
  security_level?: string;
  auth_protocol?: string;
  priv_protocol?: string;
  has_community?: boolean;
  has_auth_passphrase?: boolean;
  has_priv_passphrase?: boolean;
  weight?: number | null;
  scopes?: Record<string, unknown[]>;
  applies_to?: string[];
  invalid?: boolean;
};

type SnmpState = {
  secret_mode: 'context' | 'file';
  profiles: Profile[];
  fallback: string;
};

const EMPTY: SnmpState = { secret_mode: 'context', profiles: [], fallback: 'env' };

const MOCK: SnmpState = {
  secret_mode: 'context',
  fallback: 'env',
  profiles: [
    {
      name: 'branch-offices',
      auth: 'ie_snmp_example',
      source: 'context',
      version: '3',
      port: 161,
      security_name: 'mon-user',
      security_level: 'authPriv',
      auth_protocol: 'SHA',
      priv_protocol: 'AES',
      has_auth_passphrase: true,
      has_priv_passphrase: true,
      weight: 100,
      scopes: { sites: ['branch'] },
      applies_to: [],
    },
  ],
};

export default function SnmpTab() {
  const [state, setState] = useState<SnmpState>(EMPTY);
  const [name, setName] = useState('site-profile');
  const [version, setVersion] = useState<'2c' | '3'>('3');
  const [community, setCommunity] = useState('');
  const [securityName, setSecurityName] = useState('');
  const [authPass, setAuthPass] = useState('');
  const [privPass, setPrivPass] = useState('');
  const [deviceId, setDeviceId] = useState('');
  const [busy, setBusy] = useState(false);

  const load = () => {
    if (isMockMode()) {
      setState(MOCK);
      return;
    }
    request<SnmpState>('/api/v1/settings/snmp')
      .then(setState)
      .catch(() => toast.error('SNMP profiles could not be loaded'));
  };

  useEffect(() => {
    load();
  }, []);

  const save = () => {
    setBusy(true);
    const profile =
      version === '2c'
        ? { version, port: 161, community }
        : {
            version,
            port: 161,
            security_name: securityName,
            security_level: 'authPriv',
            auth_protocol: 'SHA',
            auth_passphrase: authPass,
            priv_protocol: 'AES',
            priv_passphrase: privPass,
          };
    const done = () => {
      setCommunity('');
      setAuthPass('');
      setPrivPass('');
      setBusy(false);
    };
    if (isMockMode()) {
      done();
      toast.success('Profile saved in this demo. Secrets are not shown again.');
      return;
    }
    request('/api/v1/settings/snmp/profiles', {
      method: 'POST',
      body: { name, weight: 100, scopes: {}, profile },
    })
      .then(() => {
        done();
        toast.success('Profile stored. Secrets are not shown again.');
        load();
      })
      .catch(() => {
        setBusy(false);
        toast.error('NetBox did not store the profile');
      });
  };

  const switchMode = (secret_mode: 'context' | 'file') => {
    if (isMockMode()) {
      setState({ ...state, secret_mode });
      return;
    }
    request('/api/v1/settings/snmp/mode', { method: 'PUT', body: { secret_mode } })
      .then(() => {
        toast.success(secret_mode === 'file' ? 'Secrets stay in the root-only file' : 'Secrets are stored in the config context');
        load();
      })
      .catch(() => toast.error('Could not change the secret mode'));
  };

  const testDevice = () => {
    if (!deviceId.trim()) return;
    setBusy(true);
    if (isMockMode()) {
      setBusy(false);
      toast.success('Demo: SNMP get was not sent');
      return;
    }
    request<{ ok?: boolean; error?: string; source?: string }>('/api/v1/settings/snmp/test', {
      method: 'POST',
      body: { device_id: Number(deviceId) },
    })
      .then((result) => {
        setBusy(false);
        if (result.ok) toast.success('SNMP get succeeded');
        else toast.error(result.error || 'SNMP get failed');
      })
      .catch(() => {
        setBusy(false);
        toast.error('SNMP test did not complete');
      });
  };

  return (
    <div className="space-y-5">
      <section className="border-y border-border bg-card shadow-card">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3">
          <div>
            <h2 className="text-base font-semibold">SNMP</h2>
            <p className="text-xs text-muted-foreground">
              Profiles live in NetBox config contexts. The most specific context with the highest weight wins. There is no per-device field.
              When a device has no <span className="font-mono">monitoring_snmp</span> context, the .env SNMP values are used.
            </p>
          </div>
          <Badge tone="neutral">{state.secret_mode === 'file' ? 'Secrets in root-only file' : 'Secrets in config context'}</Badge>
        </header>
        <div className="space-y-4 p-5">
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => switchMode('context')} className="rounded-md border border-border px-3 py-2 text-sm">
              Store secrets in the context
            </button>
            <button type="button" onClick={() => switchMode('file')} className="rounded-md border border-border px-3 py-2 text-sm">
              Context holds a profile name only
            </button>
          </div>
          <ul className="space-y-2">
            {state.profiles.length === 0 ? <li className="text-sm text-muted-foreground">No SNMP profiles yet.</li> : null}
            {state.profiles.map((profile) => (
              <li key={(profile.name || '') + (profile.auth || '')} className="rounded-md border border-border px-3 py-2 text-sm">
                <div className="font-medium">{profile.name || profile.auth || 'profile'}</div>
                <div className="text-xs text-muted-foreground">
                  {profile.version || 'unset'} · port {profile.port || 161} · {profile.security_level || 'community'} · weight {profile.weight ?? '—'} · {profile.source}
                  {profile.has_community || profile.has_auth_passphrase ? ' · secret set' : ''}
                </div>
              </li>
            ))}
          </ul>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm">
              Name
              <input value={name} onChange={(event) => setName(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-input px-3" />
            </label>
            <label className="text-sm">
              Version
              <select value={version} onChange={(event) => setVersion(event.target.value === '2c' ? '2c' : '3')} className="mt-1 h-9 w-full rounded-md border border-input px-3">
                <option value="3">3</option>
                <option value="2c">2c</option>
              </select>
            </label>
            {version === '2c' ? (
              <label className="text-sm sm:col-span-2">
                Community (write-only)
                <input type="password" autoComplete="new-password" value={community} onChange={(event) => setCommunity(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-input px-3" />
              </label>
            ) : (
              <>
                <label className="text-sm">
                  Security name
                  <input value={securityName} onChange={(event) => setSecurityName(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-input px-3" />
                </label>
                <label className="text-sm">
                  Auth passphrase (write-only)
                  <input type="password" autoComplete="new-password" value={authPass} onChange={(event) => setAuthPass(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-input px-3" />
                </label>
                <label className="text-sm sm:col-span-2">
                  Privacy passphrase (write-only)
                  <input type="password" autoComplete="new-password" value={privPass} onChange={(event) => setPrivPass(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-input px-3" />
                </label>
              </>
            )}
          </div>
          <button type="button" disabled={busy} onClick={save} className="inline-flex h-9 items-center gap-2 rounded-md bg-navy px-3 text-sm font-medium text-primary-foreground">
            <Icon name="KeyIcon" size={16} /> Save profile
          </button>
          <div className="flex flex-wrap items-end gap-2 border-t border-border pt-4">
            <label className="text-sm">
              Test device id
              <input value={deviceId} onChange={(event) => setDeviceId(event.target.value)} className="mt-1 h-9 w-40 rounded-md border border-input px-3" />
            </label>
            <button type="button" disabled={busy} onClick={testDevice} className="h-9 rounded-md border border-border px-3 text-sm">
              SNMP get
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

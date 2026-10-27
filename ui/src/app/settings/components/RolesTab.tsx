'use client';

import React, { useState } from 'react';
import { toast } from 'sonner';
import Icon from '@/components/ui/AppIcon';
import Badge from '@/components/ui/Badge';
import { PERMISSIONS, USERS } from '@/lib/mockData';
import type { RoleName, UserRow } from '@/lib/types';

const ROLES: RoleName[] = ['Administrator', 'Engineer', 'Operator', 'Read-only'];
const ROLE_NOTE: Record<RoleName, string> = {
  Administrator: 'Full control, including users, roles and the webhook',
  Engineer: 'Approve devices, change thresholds, acknowledge alerts',
  Operator: 'Watch and acknowledge alerts; cannot change inventory',
  'Read-only': 'View devices, faceplates and graphs only',
};
const ROLE_TONE: Record<RoleName, 'destructive' | 'info' | 'cyan' | 'neutral'> = {
  Administrator: 'destructive',
  Engineer: 'info',
  Operator: 'cyan',
  'Read-only': 'neutral',
};

export default function RolesTab() {
  const [users, setUsers] = useState<UserRow[]>(USERS);

  const setRole = (id: string, role: RoleName) => {
    setUsers((u) => u.map((x) => (x.id === id ? { ...x, role } : x)));
    toast.success('Role updated');
  };

  return (
    <div className="space-y-5">
      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-labelledby="perm-title">
        <header className="border-b border-border px-5 py-3">
          <h2 id="perm-title" className="text-base font-semibold">Permission matrix</h2>
          <p className="text-xs text-muted-foreground">What each role can do. Change a user's role below.</p>
        </header>
        <div className="scroll-thin overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/60 text-left">
                <th scope="col" className="px-5 py-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Permission</th>
                {ROLES.map((r) => (
                  <th key={`ph-${r}`} scope="col" className="px-3 py-3 text-center">
                    <span className="block text-xs font-semibold">{r}</span>
                    <span className="mx-auto mt-0.5 block max-w-[150px] text-[10px] font-normal leading-tight text-muted-foreground">{ROLE_NOTE[r]}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {PERMISSIONS.map((p) => (
                <tr key={p.label} className="border-b border-border even:bg-muted/20">
                  <th scope="row" className="px-5 py-2.5 text-left text-sm font-normal">{p.label}</th>
                  {ROLES.map((r) => (
                    <td key={`${p.label}-${r}`} className="px-3 py-2.5 text-center">
                      {p[r] ? (
                        <span className="inline-flex items-center gap-1 text-success" title="Allowed">
                          <Icon name="CheckCircleIcon" size={18} variant="solid" />
                          <span className="sr-only">Allowed</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-muted-foreground" title="Not allowed">
                          <Icon name="MinusIcon" size={18} />
                          <span className="sr-only">Not allowed</span>
                        </span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-labelledby="users-title">
        <header className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 id="users-title" className="text-base font-semibold">Users</h2>
            <p className="text-xs text-muted-foreground">{users.length} users · 4 with MFA enabled</p>
          </div>
          <button
            type="button"
            onClick={() => toast.success('Invitation link copied to clipboard')}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-all hover:opacity-90 active:scale-95"
          >
            <Icon name="UserPlusIcon" size={16} /> Invite user
          </button>
        </header>
        <div className="scroll-thin overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th scope="col" className="px-5 py-2.5">User</th>
                <th scope="col" className="px-3 py-2.5">Role</th>
                <th scope="col" className="px-3 py-2.5">MFA</th>
                <th scope="col" className="px-3 py-2.5">Last active</th>
                <th scope="col" className="px-3 py-2.5 text-right">Change role</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-border transition-colors even:bg-muted/20 hover:bg-accent/10">
                  <td className="px-5 py-2.5">
                    <div className="flex items-center gap-3">
                      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-navy text-xs font-bold text-cyan">
                        {u.name.split(' ').map((n) => n[0]).slice(0, 2).join('')}
                      </span>
                      <div className="min-w-0">
                        <p className="truncate font-medium">{u.name}</p>
                        <p className="truncate font-mono-data text-xs text-muted-foreground">{u.email}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2.5"><Badge tone={ROLE_TONE[u.role]}>{u.role}</Badge></td>
                  <td className="px-3 py-2.5">
                    {u.mfa ? (
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-success"><Icon name="ShieldCheckIcon" size={14} variant="solid" /> Enabled</span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-warning-foreground"><Icon name="ExclamationTriangleIcon" size={14} variant="solid" /> Not set up</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-xs text-muted-foreground">{u.lastActive}</td>
                  <td className="px-3 py-2.5 text-right">
                    <label>
                      <span className="sr-only">Role for {u.name}</span>
                      <select value={u.role} onChange={(e) => setRole(u.id, e.target.value as RoleName)} className="h-8 rounded-md border border-input bg-card px-2 text-sm">
                        {ROLES.map((r) => (
                          <option key={`${u.id}-${r}`} value={r}>{r}</option>
                        ))}
                      </select>
                    </label>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
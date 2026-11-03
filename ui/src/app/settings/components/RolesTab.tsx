'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import Icon from '@/components/ui/AppIcon';
import Badge from '@/components/ui/Badge';
import Modal from '@/components/ui/Modal';
import { PERMISSIONS } from '@/lib/mockData';
import { api } from '@/lib/apiClient';
import { isApiError } from '@/lib/apiError';
import type { DirectoryUser, UserAuditEntry } from '@/lib/contract';
import { canManageUsers } from '@/lib/settings/access';
import { useSession } from '@/lib/useSession';

const ROLES = ['Administrator', 'Engineer', 'Operator', 'Read-only'] as const;
type MatrixRole = (typeof ROLES)[number];
const ROLE_LABEL: Record<string, string> = {
  Administrator: 'Administrator (Admin)',
  Admin: 'Administrator (Admin)',
  Engineer: 'Engineer',
  Operator: 'Operator',
  'Read-only': 'Read-only (Viewer)',
  Viewer: 'Read-only (Viewer)',
};
const ROLE_NOTE: Record<string, string> = {
  Administrator: 'Admin. Users, Settings, and Vault',
  Engineer: 'Settings except Vault and users. Can edit devices',
  Operator: 'NetBridge syncs, alerts, and device edits. No Users or Vault',
  'Read-only': 'Viewer. Read-only',
};
const ROLE_TONE: Record<string, 'destructive' | 'info' | 'cyan' | 'neutral'> = {
  Administrator: 'destructive',
  Admin: 'destructive',
  Engineer: 'info',
  Operator: 'cyan',
  'Read-only': 'neutral',
  Viewer: 'neutral',
};

function stamp(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}

function message(cause: unknown, fallback: string): string {
  return isApiError(cause) ? cause.message : fallback;
}

function isAdminRole(role: string): boolean {
  return role === 'Administrator' || role === 'Admin';
}

export default function RolesTab() {
  const { role, session, ready } = useSession();
  const manage = ready && canManageUsers(role);
  const [users, setUsers] = useState<DirectoryUser[]>([]);
  const [audit, setAudit] = useState<UserAuditEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<DirectoryUser | null>(null);
  const [resetting, setResetting] = useState<DirectoryUser | null>(null);
  const [removing, setRemoving] = useState<DirectoryUser | null>(null);
  const [once, setOnce] = useState<string | null>(null);

  const load = () => {
    if (!manage) return;
    Promise.all([api.listDirectoryUsers(), api.listUserAudit()])
      .then(([rows, log]) => {
        setUsers(rows);
        setAudit(log.entries);
        setError(null);
      })
      .catch((cause) => setError(message(cause, 'Users could not be loaded.')));
  };

  useEffect(() => {
    load();
    // The directory is loaded when the signed-in role is known.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [manage]);

  const activeAdmins = useMemo(
    () => users.filter((user) => user.status === 'active' && isAdminRole(user.role)).length,
    [users]
  );

  return (
    <div className="space-y-5">
      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-labelledby="perm-title">
        <header className="border-b border-border px-5 py-3">
          <h2 id="perm-title" className="text-base font-semibold">Permission matrix</h2>
          <p className="text-xs text-muted-foreground">
            Administrator is Admin, Read-only is Viewer, and Operator can approve NetBridge syncs,
            acknowledge alerts, and edit devices. Engineer keeps Settings access except Vault and users.
          </p>
        </header>
        <div className="scroll-thin overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/60 text-left">
                <th scope="col" className="px-5 py-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Permission</th>
                {ROLES.map((item) => (
                  <th key={`ph-${item}`} scope="col" className="px-3 py-3 text-center">
                    <span className="block text-xs font-semibold">{ROLE_LABEL[item]}</span>
                    <span className="mx-auto mt-0.5 block max-w-[150px] text-[10px] font-normal leading-tight text-muted-foreground">{ROLE_NOTE[item]}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {PERMISSIONS.map((row) => (
                <tr key={row.label} className="border-b border-border even:bg-muted/20">
                  <th scope="row" className="px-5 py-2.5 text-left text-sm font-normal">{row.label}</th>
                  {ROLES.map((item) => (
                    <td key={`${row.label}-${item}`} className="px-3 py-2.5 text-center">
                      {row[item] ? (
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
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3">
          <div>
            <h2 id="users-title" className="text-base font-semibold">Users</h2>
            <p className="text-xs text-muted-foreground">
              {manage ? `${users.length} ${users.length === 1 ? 'user' : 'users'}` : 'Only an Administrator can change users.'}
            </p>
          </div>
          {manage ? (
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-all hover:opacity-90 active:scale-95"
            >
              <Icon name="UserPlusIcon" size={16} /> Add user
            </button>
          ) : null}
        </header>
        {!manage ? (
          <p className="px-5 py-6 text-sm text-muted-foreground">
            Sign in as an Administrator to add users, change roles, reset passwords, or disable an account.
          </p>
        ) : error ? (
          <div role="alert" className="m-4 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{error}</div>
        ) : (
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[980px] text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th scope="col" className="px-5 py-2.5">Username</th>
                  <th scope="col" className="px-3 py-2.5">Name</th>
                  <th scope="col" className="px-3 py-2.5">Email</th>
                  <th scope="col" className="px-3 py-2.5">Role</th>
                  <th scope="col" className="px-3 py-2.5">Status</th>
                  <th scope="col" className="px-3 py-2.5">Last login</th>
                  <th scope="col" className="px-3 py-2.5">Created</th>
                  <th scope="col" className="px-3 py-2.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => {
                  const locked = user.builtin || user.username === 'admin';
                  const lastAdmin = isAdminRole(user.role) && user.status === 'active' && activeAdmins <= 1;
                  const self = session?.email === user.email || session?.id === user.id;
                  return (
                    <tr key={user.id} className="border-b border-border transition-colors even:bg-muted/20 hover:bg-accent/10">
                      <td className="px-5 py-2.5 font-mono-data text-xs">{user.username}</td>
                      <td className="px-3 py-2.5 font-medium">{user.displayName}</td>
                      <td className="px-3 py-2.5 text-muted-foreground">{user.email}</td>
                      <td className="px-3 py-2.5"><Badge tone={ROLE_TONE[user.role] || 'neutral'}>{ROLE_LABEL[user.role] || user.role}</Badge></td>
                      <td className="px-3 py-2.5">
                        <Badge tone={user.status === 'active' ? 'success' : 'neutral'}>{user.status === 'active' ? 'Active' : 'Disabled'}</Badge>
                        {user.mustChangePassword ? <span className="ml-2 text-xs text-muted-foreground">Password change required</span> : null}
                      </td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground">{stamp(user.lastLogin)}</td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground">{stamp(user.created)}</td>
                      <td className="px-3 py-2.5">
                        <div className="flex justify-end gap-1">
                          <button type="button" className="rounded-md border border-border px-2 py-1 text-xs" onClick={() => setEditing(user)}>Edit</button>
                          <button
                            type="button"
                            className="rounded-md border border-border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-40"
                            disabled={locked || (lastAdmin && user.status === 'active')}
                            title={locked ? 'The built-in admin account cannot be disabled' : lastAdmin ? 'The last administrator cannot be disabled' : ''}
                            onClick={() => toggleStatus(user)}
                          >
                            {user.status === 'active' ? 'Disable' : 'Enable'}
                          </button>
                          <button type="button" className="rounded-md border border-border px-2 py-1 text-xs" onClick={() => setResetting(user)}>Reset password</button>
                          <button
                            type="button"
                            className="rounded-md border border-destructive/40 px-2 py-1 text-xs text-destructive disabled:cursor-not-allowed disabled:opacity-40"
                            disabled={locked || lastAdmin || self || busy}
                            title={locked ? 'The built-in admin account cannot be deleted' : self ? 'You cannot delete your own account' : lastAdmin ? 'The last administrator cannot be deleted' : ''}
                            onClick={() => setRemoving(user)}
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-labelledby="audit-title">
        <header className="border-b border-border px-5 py-3">
          <h2 id="audit-title" className="text-base font-semibold">User audit</h2>
          <p className="text-xs text-muted-foreground">Who changed a user, when, and what changed. Passwords are not stored here.</p>
        </header>
        {manage ? (
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th scope="col" className="px-5 py-2.5">When</th>
                  <th scope="col" className="px-3 py-2.5">Who</th>
                  <th scope="col" className="px-3 py-2.5">Action</th>
                  <th scope="col" className="px-3 py-2.5">What</th>
                </tr>
              </thead>
              <tbody>
                {audit.length === 0 ? (
                  <tr><td colSpan={4} className="px-5 py-4 text-sm text-muted-foreground">No user changes yet.</td></tr>
                ) : audit.map((row) => (
                  <tr key={row.id} className="border-b border-border even:bg-muted/20">
                    <td className="px-5 py-2.5 text-xs text-muted-foreground">{stamp(row.at)}</td>
                    <td className="px-3 py-2.5">{row.actor || '—'}</td>
                    <td className="px-3 py-2.5 font-mono-data text-xs">{row.action}</td>
                    <td className="px-3 py-2.5 text-muted-foreground">{row.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="px-5 py-6 text-sm text-muted-foreground">The audit log is visible to Administrators.</p>
        )}
      </section>

      <AddUser
        open={adding}
        busy={busy}
        onClose={() => setAdding(false)}
        onSubmit={async (body) => {
          setBusy(true);
          try {
            const created = await api.createDirectoryUser(body);
            setAdding(false);
            if (created.oneTimePassword) setOnce(created.oneTimePassword);
            else toast.success('User added');
            load();
          } catch (cause) {
            toast.error(message(cause, 'The user was not added.'));
          } finally {
            setBusy(false);
          }
        }}
      />
      <EditUser
        user={editing}
        locked={!!editing && (editing.builtin || editing.username === 'admin' || (isAdminRole(editing.role) && editing.status === 'active' && activeAdmins <= 1))}
        busy={busy}
        onClose={() => setEditing(null)}
        onSubmit={async (body) => {
          if (!editing) return;
          setBusy(true);
          try {
            await api.updateDirectoryUser(editing.id, body);
            setEditing(null);
            toast.success('User updated');
            load();
          } catch (cause) {
            toast.error(message(cause, 'The user was not updated.'));
          } finally {
            setBusy(false);
          }
        }}
      />
      <ResetPassword
        user={resetting}
        busy={busy}
        onClose={() => setResetting(null)}
        onSubmit={async (body) => {
          if (!resetting) return;
          setBusy(true);
          try {
            const result = await api.resetDirectoryPassword(resetting.id, body);
            setResetting(null);
            if (result.oneTimePassword) setOnce(result.oneTimePassword);
            else toast.success('Password reset. The user must change it at the next sign-in.');
            load();
          } catch (cause) {
            toast.error(message(cause, 'The password was not reset.'));
          } finally {
            setBusy(false);
          }
        }}
      />
      <Modal
        open={!!removing}
        onClose={() => !busy && setRemoving(null)}
        title="Delete user"
        description={removing ? `Delete ${removing.username}? This cannot be undone.` : ''}
        footer={
          <>
            <button type="button" className="rounded-md border border-border px-3 py-1.5 text-sm" onClick={() => setRemoving(null)}>Cancel</button>
            <button
              type="button"
              disabled={busy}
              className="rounded-md bg-destructive px-3 py-1.5 text-sm font-semibold text-destructive-foreground"
              onClick={async () => {
                if (!removing) return;
                setBusy(true);
                try {
                  await api.deleteDirectoryUser(removing.id);
                  setRemoving(null);
                  toast.success('User deleted');
                  load();
                } catch (cause) {
                  toast.error(message(cause, 'The user was not deleted.'));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Delete user
            </button>
          </>
        }
      />
      <Modal
        open={!!once}
        onClose={() => setOnce(null)}
        title="One-time password"
        description="Copy this password now. It is not shown again and it is not written to the audit log."
      >
        <p className="break-all rounded-md border border-border bg-muted px-3 py-2 font-mono-data text-sm">{once}</p>
      </Modal>
    </div>
  );

  async function toggleStatus(user: DirectoryUser) {
    setBusy(true);
    try {
      await api.setDirectoryUserStatus(user.id, user.status === 'active' ? 'disabled' : 'active');
      toast.success(user.status === 'active' ? 'User disabled' : 'User enabled');
      load();
    } catch (cause) {
      toast.error(message(cause, 'The status was not changed.'));
    } finally {
      setBusy(false);
    }
  }
}

function AddUser({
  open,
  busy,
  onClose,
  onSubmit,
}: {
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onSubmit: (body: { username: string; displayName: string; email: string; role: string; password?: string; generate?: boolean; forceChange?: boolean }) => Promise<void>;
}) {
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<MatrixRole>('Operator');
  const [password, setPassword] = useState('');
  const [generate, setGenerate] = useState(true);
  const [forceChange, setForceChange] = useState(true);
  useEffect(() => {
    if (!open) return;
    setUsername('');
    setDisplayName('');
    setEmail('');
    setRole('Operator');
    setPassword('');
    setGenerate(true);
    setForceChange(true);
  }, [open]);
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add user"
      description="The password is hashed and is not written to the audit log."
      footer={
        <>
          <button type="button" className="rounded-md border border-border px-3 py-1.5 text-sm" onClick={onClose}>Cancel</button>
          <button
            type="button"
            disabled={busy}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground"
            onClick={() => onSubmit({ username, displayName, email, role, password: generate ? undefined : password, generate, forceChange: forceChange || generate })}
          >
            Add user
          </button>
        </>
      }
    >
      <UserFields
        username={username}
        displayName={displayName}
        email={email}
        role={role}
        onUsername={setUsername}
        onName={setDisplayName}
        onEmail={setEmail}
        onRole={setRole}
      />
      <label className="mt-3 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={generate} onChange={(event) => setGenerate(event.target.checked)} />
        Generate a one-time password
      </label>
      {generate ? null : (
        <label className="mt-3 block text-sm">
          Initial password
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="new-password" className="mt-1 h-9 w-full rounded-md border border-input px-3" />
          <span className="mt-1 block text-xs text-muted-foreground">12 or more characters, with a letter and a digit.</span>
        </label>
      )}
      <label className="mt-3 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={forceChange || generate} disabled={generate} onChange={(event) => setForceChange(event.target.checked)} />
        Require a password change at the next sign-in
      </label>
    </Modal>
  );
}

function EditUser({
  user,
  locked,
  busy,
  onClose,
  onSubmit,
}: {
  user: DirectoryUser | null;
  locked: boolean;
  busy: boolean;
  onClose: () => void;
  onSubmit: (body: { displayName: string; email: string; role: string }) => Promise<void>;
}) {
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<MatrixRole>('Operator');
  useEffect(() => {
    if (!user) return;
    setDisplayName(user.displayName);
    setEmail(user.email);
    const stored = user.role === 'Admin' ? 'Administrator' : user.role === 'Viewer' ? 'Read-only' : user.role;
    setRole(stored === 'Engineer' || stored === 'Operator' || stored === 'Read-only' || stored === 'Administrator' ? stored : 'Operator');
  }, [user]);
  return (
    <Modal
      open={!!user}
      onClose={onClose}
      title={user ? `Edit ${user.username}` : 'Edit user'}
      description={locked ? 'This account stays an Administrator.' : 'Role, name, and email can be changed.'}
      footer={
        <>
          <button type="button" className="rounded-md border border-border px-3 py-1.5 text-sm" onClick={onClose}>Cancel</button>
          <button type="button" disabled={busy} className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground" onClick={() => onSubmit({ displayName, email, role })}>Save</button>
        </>
      }
    >
      <UserFields
        username={user?.username || ''}
        displayName={displayName}
        email={email}
        role={role}
        lockRole={locked}
        lockUsername
        onUsername={() => undefined}
        onName={setDisplayName}
        onEmail={setEmail}
        onRole={setRole}
      />
    </Modal>
  );
}

function ResetPassword({
  user,
  busy,
  onClose,
  onSubmit,
}: {
  user: DirectoryUser | null;
  busy: boolean;
  onClose: () => void;
  onSubmit: (body: { password?: string; generate?: boolean }) => Promise<void>;
}) {
  const [generate, setGenerate] = useState(true);
  const [password, setPassword] = useState('');
  useEffect(() => {
    if (!user) return;
    setGenerate(true);
    setPassword('');
  }, [user]);
  return (
    <Modal
      open={!!user}
      onClose={onClose}
      title={user ? `Reset password for ${user.username}` : 'Reset password'}
      description="Existing sessions for this user are signed out. The new password must be changed at the next sign-in."
      footer={
        <>
          <button type="button" className="rounded-md border border-border px-3 py-1.5 text-sm" onClick={onClose}>Cancel</button>
          <button type="button" disabled={busy} className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground" onClick={() => onSubmit(generate ? { generate: true } : { password })}>Reset password</button>
        </>
      }
    >
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={generate} onChange={(event) => setGenerate(event.target.checked)} />
        Generate a one-time password
      </label>
      {generate ? null : (
        <label className="mt-3 block text-sm">
          New password
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="new-password" className="mt-1 h-9 w-full rounded-md border border-input px-3" />
        </label>
      )}
    </Modal>
  );
}

function UserFields({
  username,
  displayName,
  email,
  role,
  lockUsername,
  lockRole,
  onUsername,
  onName,
  onEmail,
  onRole,
}: {
  username: string;
  displayName: string;
  email: string;
  role: MatrixRole;
  lockUsername?: boolean;
  lockRole?: boolean;
  onUsername: (value: string) => void;
  onName: (value: string) => void;
  onEmail: (value: string) => void;
  onRole: (value: MatrixRole) => void;
}) {
  return (
    <div className="grid gap-3">
      <label className="block text-sm">
        Username
        <input value={username} disabled={lockUsername} onChange={(event) => onUsername(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-input px-3 disabled:bg-muted" />
      </label>
      <label className="block text-sm">
        Name
        <input value={displayName} onChange={(event) => onName(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-input px-3" />
      </label>
      <label className="block text-sm">
        Email
        <input value={email} onChange={(event) => onEmail(event.target.value)} type="email" className="mt-1 h-9 w-full rounded-md border border-input px-3" />
      </label>
      <label className="block text-sm">
        Role
        <select
          value={role}
          disabled={lockRole}
          onChange={(event) => onRole(event.target.value as MatrixRole)}
          className="mt-1 h-9 w-full rounded-md border border-input bg-card px-2 disabled:bg-muted"
        >
          {ROLES.map((item) => (
            <option key={item} value={item}>{ROLE_LABEL[item]}</option>
          ))}
        </select>
      </label>
    </div>
  );
}

'use client';

import React, { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import Icon from '@/components/ui/AppIcon';
import { api } from '@/lib/apiClient';
import { displayInitials, displayName, readSession, subscribeSession } from '@/lib/session';

interface TopbarProps {
  onOpenMobile: () => void;
  onOpenSearch: () => void;
}

export default function Topbar({ onOpenMobile, onOpenSearch }: TopbarProps) {
  const [now, setNow] = useState('');
  const [menu, setMenu] = useState(false);
  const [alerts, setAlerts] = useState(0);
  const [setup, setSetup] = useState('');
  const [who, setWho] = useState({ name: '', role: '', initials: '' });
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const fmt = () => {
      const d = new Date();
      const p = (n: number) => String(n).padStart(2, '0');
      setNow(`${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} UTC`);
    };
    fmt();
    const id = setInterval(fmt, 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const apply = () => {
      const session = readSession();
      if (!session) {
        setWho({ name: '', role: '', initials: '' });
        return;
      }
      setWho({ name: displayName(session.email), role: session.role, initials: displayInitials(session.email) });
    };
    apply();
    return subscribeSession(apply);
  }, []);

  useEffect(() => {
    let cancelled = false;
    api.getSummary().then((summary) => {
      if (!cancelled) setAlerts(Number(summary.alerts) || 0);
    }).catch(() => {
      if (!cancelled) setAlerts(0);
    });
    api.getSetupState().then((state) => {
      if (!cancelled) setSetup(state.state === 'complete' ? 'Setup complete' : `Setup ${state.state}`);
    }).catch(() => {
      if (!cancelled) setSetup('');
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const signOut = async () => {
    try {
      await api.logout();
    } catch {
      /* local session is cleared even if the server is unreachable */
    }
    window.location.assign('/login-screen');
  };

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenu(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-card/90 px-4 backdrop-blur lg:px-6">
      <button
        type="button"
        onClick={onOpenMobile}
        aria-label="Open navigation"
        className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted md:hidden"
      >
        <Icon name="Bars3Icon" size={20} />
      </button>

      <button
        type="button"
        onClick={onOpenSearch}
        className="flex h-10 w-full max-w-md items-center gap-2 rounded-md border border-input bg-background px-3 text-sm text-muted-foreground transition-colors hover:border-ring"
      >
        <Icon name="MagnifyingGlassIcon" size={16} />
        <span className="flex-1 truncate text-left">Search devices, sites, IPs, ports…</span>
        <kbd className="hidden rounded border border-border bg-card px-1.5 py-0.5 font-mono-data text-[11px] sm:inline">Ctrl K</kbd>
      </button>

      <div className="ml-auto flex items-center gap-2 sm:gap-3">
        {setup ? (
          <div className="hidden items-center gap-1.5 rounded-full border border-success/30 bg-success/10 px-2.5 py-1 text-xs font-medium text-success lg:flex" title="GET /setup/state">
            <Icon name="CheckBadgeIcon" size={14} variant="solid" />
            {setup}
          </div>
        ) : null}
        <div className="hidden items-center gap-1.5 text-xs text-muted-foreground md:flex">
          <span className="relative flex h-2 w-2">
            <span className="pulse-ring absolute inline-flex h-full w-full rounded-full bg-teal" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-teal" />
          </span>
          Live
          <span className="font-mono-data text-foreground" suppressHydrationWarning>
            {now || '--:--:-- UTC'}
          </span>
        </div>
        <Link
          href="/alerts"
          aria-label={alerts ? `${alerts} alerts firing` : 'Alerts'}
          className="relative rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <Icon name="BellAlertIcon" size={20} variant="outline" />
          {alerts > 0 ? (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-bold tabular text-destructive-foreground">
              {alerts > 99 ? '99+' : alerts}
            </span>
          ) : null}
        </Link>

        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenu((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={menu}
            className="flex items-center gap-2 rounded-md p-1 pr-2 transition-colors hover:bg-muted"
          >
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-navy text-xs font-bold text-cyan">{who.initials || '—'}</span>
            <Icon name="ChevronDownIcon" size={14} className="text-muted-foreground" />
          </button>
          {menu && (
            <div role="menu" className="absolute right-0 top-full z-50 mt-2 w-56 rounded-lg border border-border bg-card p-1 shadow-pop pop-in">
              <div className="border-b border-border px-3 py-2">
                <p className="text-sm font-medium">{who.name || 'Signed out'}</p>
                <p className="text-xs text-muted-foreground">{who.role || 'No session'}</p>
              </div>
              <Link href="/settings" role="menuitem" className="flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-muted">
                <Icon name="Cog6ToothIcon" size={16} /> Settings
              </Link>
              <button type="button" role="menuitem" onClick={signOut} className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-muted">
                <Icon name="ArrowRightOnRectangleIcon" size={16} /> Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
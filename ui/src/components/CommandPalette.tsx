'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Icon from '@/components/ui/AppIcon';

interface Entry {
  id: string;
  label: string;
  hint: string;
  href: string;
  icon: string;
}

const ENTRIES: Entry[] = [
  { id: 'cmd-dev', label: 'All devices', hint: 'Device list · 19,840 devices', href: '/', icon: 'ServerStackIcon' },
  { id: 'cmd-detail', label: 'stk-rot04-01', hint: 'Switch stack · Rotterdam-Havenstraat-214 · 10.22.14.17', href: '/device-detail', icon: 'CpuChipIcon' },
  { id: 'cmd-site', label: 'Rotterdam-Havenstraat-214', hint: 'Site · 9 devices', href: '/site-view', icon: 'BuildingOffice2Icon' },
  { id: 'cmd-nib', label: 'Not in NetBox', hint: '10 discovered devices awaiting approval', href: '/not-in-net-box', icon: 'QuestionMarkCircleIcon' },
  { id: 'cmd-fw', label: 'fw-ams01-a', hint: 'Firewall · Amsterdam-Zuidas-105 · Te0/2 faulted', href: '/device-detail', icon: 'ShieldExclamationIcon' },
  { id: 'cmd-set', label: 'Settings', hint: 'Roles, database, Alertmanager webhook', href: '/settings', icon: 'Cog6ToothIcon' },
  { id: 'cmd-ip', label: '10.22.14.61', hint: 'IP · sw-rot04-09 (discovered)', href: '/not-in-net-box', icon: 'GlobeAltIcon' },
];

export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const results = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return ENTRIES;
    return ENTRIES.filter((e) => e.label.toLowerCase().includes(s) || e.hint.toLowerCase().includes(s));
  }, [q]);

  useEffect(() => {
    if (open) {
      setQ('');
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 20);
    }
  }, [open]);

  useEffect(() => {
    setActive(0);
  }, [q]);

  if (!open) return null;

  const go = (e: Entry) => {
    onClose();
    router.push(e.href);
  };

  return (
    <div className="fixed inset-0 z-[90] flex items-start justify-center p-4 pt-[12vh]">
      <div className="absolute inset-0 bg-navy/60 fade-in" onClick={onClose} aria-hidden="true" />
      <div role="dialog" aria-modal="true" aria-label="Global search" className="relative w-full max-w-xl overflow-hidden rounded-lg border border-border bg-card shadow-pop pop-in">
        <div className="flex items-center gap-2 border-b border-border px-4">
          <Icon name="MagnifyingGlassIcon" size={18} className="text-muted-foreground" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') onClose();
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                setActive((a) => Math.min(results.length - 1, a + 1));
              }
              if (e.key === 'ArrowUp') {
                e.preventDefault();
                setActive((a) => Math.max(0, a - 1));
              }
              if (e.key === 'Enter' && results[active]) go(results[active]);
            }}
            placeholder="Search hostname, IP, site, port…"
            aria-label="Search"
            className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          <kbd className="rounded border border-border px-1.5 py-0.5 font-mono-data text-[11px] text-muted-foreground">Esc</kbd>
        </div>
        <ul className="scroll-thin max-h-80 overflow-y-auto p-1.5" role="listbox">
          {results.length === 0 && <li className="px-3 py-8 text-center text-sm text-muted-foreground">No devices, sites or IPs match “{q}”.</li>}
          {results.map((r, i) => (
            <li key={r.id} role="option" aria-selected={i === active}>
              <button
                type="button"
                onMouseEnter={() => setActive(i)}
                onClick={() => go(r)}
                className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-left transition-colors ${i === active ? 'bg-accent/15' : ''}`}
              >
                <span className="flex h-8 w-8 items-center justify-center rounded-md bg-muted text-muted-foreground">
                  <Icon name={r.icon} size={16} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium font-mono-data">{r.label}</span>
                  <span className="block truncate text-xs text-muted-foreground">{r.hint}</span>
                </span>
                {i === active && <Icon name="ArrowUturnLeftIcon" size={14} className="text-muted-foreground" />}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
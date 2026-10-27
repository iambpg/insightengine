'use client';

import React, { useEffect, useRef, useState } from 'react';
import Icon from '@/components/ui/AppIcon';

export type ColumnKey =
  | 'health' |'hostname' |'role' |'site' |'mgmtIp' |'modelFamily' |'ports' |'faults' |'uptime' |'lastPoll';

export const COLUMNS: { key: ColumnKey; label: string; locked?: boolean }[] = [
  { key: 'health', label: 'Health', locked: true },
  { key: 'hostname', label: 'Hostname', locked: true },
  { key: 'role', label: 'Role' },
  { key: 'site', label: 'Site' },
  { key: 'mgmtIp', label: 'Management IP' },
  { key: 'modelFamily', label: 'Model family' },
  { key: 'ports', label: 'Ports up / total' },
  { key: 'faults', label: 'Warn / fault ports' },
  { key: 'uptime', label: 'Uptime' },
  { key: 'lastPoll', label: 'Last poll' },
];

interface Props {
  visible: ColumnKey[];
  onChange: (v: ColumnKey[]) => void;
}

export default function ColumnMenu({ visible, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const toggle = (k: ColumnKey) => {
    onChange(visible.includes(k) ? visible.filter((v) => v !== k) : [...visible, k]);
  };

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-sm font-medium transition-all hover:bg-muted active:scale-95"
      >
        <Icon name="ViewColumnsIcon" size={16} />
        Columns
        <span className="rounded bg-muted px-1.5 text-xs tabular text-muted-foreground">{visible.length}/{COLUMNS.length}</span>
      </button>
      {open && (
        <div role="menu" className="pop-in absolute right-0 top-full z-40 mt-2 w-56 rounded-lg border border-border bg-card p-2 shadow-pop">
          <p className="label-caps px-2 pb-1 text-muted-foreground">Visible columns</p>
          {COLUMNS.map((c) => (
            <label key={`col-${c.key}`} className={`flex items-center gap-2 rounded-md px-2 py-1.5 text-sm ${c.locked ? 'opacity-60' : 'cursor-pointer hover:bg-muted'}`}>
              <input
                type="checkbox"
                checked={visible.includes(c.key)}
                disabled={c.locked}
                onChange={() => toggle(c.key)}
                className="h-4 w-4 accent-[var(--primary)]"
              />
              {c.label}
              {c.locked && <span className="ml-auto text-[10px] text-muted-foreground">fixed</span>}
            </label>
          ))}
          <button
            type="button"
            onClick={() => onChange(COLUMNS.map((c) => c.key))}
            className="mt-1 w-full rounded-md px-2 py-1.5 text-left text-xs font-medium text-primary hover:bg-muted"
          >
            Show all columns
          </button>
        </div>
      )}
    </div>
  );
}
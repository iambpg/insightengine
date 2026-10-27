'use client';

import React, { useEffect, useState } from 'react';
import Icon from '@/components/ui/AppIcon';
import type { DeviceQuery } from '@/lib/apiClient';

interface Props {
  query: DeviceQuery;
  onChange: (p: Partial<DeviceQuery>) => void;
}

const ROLES = ['all', 'Access switch', 'Switch stack', 'Access point', 'Wireless controller', 'Firewall', 'Branch router', 'Modular chassis'];
const HEALTH = ['all', 'healthy', 'warning', 'critical', 'unreachable'] as const;

export default function DeviceFilters({ query, onChange }: Props) {
  const [text, setText] = useState(query.search);

  useEffect(() => {
    setText(query.search);
  }, [query.search]);

  // debounce typing so large lists do not refetch on every key
  useEffect(() => {
    if (text === query.search) return;
    const id = setTimeout(() => onChange({ search: text }), 250);
    return () => clearTimeout(id);
  }, [text, query.search, onChange]);

  return (
    <>
      <label className="relative min-w-[220px] flex-1 sm:max-w-sm">
        <span className="sr-only">Search devices</span>
        <Icon name="MagnifyingGlassIcon" size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Hostname, IP or site…"
          className="h-9 w-full rounded-md border border-input bg-background pl-9 pr-3 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-ring"
        />
      </label>

      <label className="flex items-center gap-1.5 text-sm">
        <span className="text-muted-foreground">Role</span>
        <select
          value={query.role}
          onChange={(e) => onChange({ role: e.target.value })}
          className="h-9 rounded-md border border-input bg-card px-2 text-sm"
        >
          {ROLES.map((r) => (
            <option key={`role-${r}`} value={r}>
              {r === 'all' ? 'All roles' : r}
            </option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-1.5 text-sm">
        <span className="text-muted-foreground">Health</span>
        <select
          value={query.health}
          onChange={(e) => onChange({ health: e.target.value as DeviceQuery['health'] })}
          className="h-9 rounded-md border border-input bg-card px-2 text-sm"
        >
          {HEALTH.map((h) => (
            <option key={`health-${h}`} value={h}>
              {h === 'all' ? 'All health states' : h.charAt(0).toUpperCase() + h.slice(1)}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}
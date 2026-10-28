'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import Icon from '@/components/ui/AppIcon';
import AppLogo from '@/components/ui/AppLogo';
import { api } from '@/lib/apiClient';
import { reportLoadError } from '@/lib/loadError';
import { isMockMode } from '@/lib/apiMode';
import { displayInitials, displayName, readSession, subscribeSession } from '@/lib/session';

interface NavItem {
  href: string;
  label: string;
  icon: string;
  badge?: number;
}

const GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: 'Monitor',
    items: [
      { href: '/', label: 'Devices', icon: 'ServerStackIcon' },
      { href: '/device-detail', label: 'Device detail', icon: 'CpuChipIcon' },
      { href: '/site-view', label: 'Sites', icon: 'BuildingOffice2Icon' },
      { href: '/alerts', label: 'Alerts', icon: 'BellAlertIcon' },
    ],
  },
  {
    title: 'Inventory',
    items: [
      {
        href: '/not-in-net-box',
        label: 'Not in NetBox',
        icon: 'QuestionMarkCircleIcon',
      },
    ],
  },
  {
    title: 'Administration',
    items: [
      { href: '/device-cli', label: 'Device CLI', icon: 'CommandLineIcon' },
      { href: '/topology', label: 'Topology', icon: 'ShareIcon' },
      { href: '/settings', label: 'Settings', icon: 'Cog6ToothIcon' },
    ],
  },
];

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export default function Sidebar({ collapsed, onToggle, mobileOpen, onCloseMobile }: SidebarProps) {
  const pathname = usePathname();
  const [who, setWho] = useState({
    name: 'Marit van der Berg',
    role: 'Administrator',
    initials: 'MB',
  });
  const [pending, setPending] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api
      .listDiscovered()
      .then((rows) => {
        if (!cancelled) setPending(rows.length);
      })
      .catch((cause) => {
        reportLoadError(cause, 'discovered devices');
        if (!cancelled) setPending(0);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const apply = () => {
      const session = readSession();
      if (!session) {
        setWho(
          isMockMode()
            ? { name: 'Marit van der Berg', role: 'Administrator', initials: 'MB' }
            : { name: 'Signed out', role: '', initials: '—' }
        );
        return;
      }
      const name = displayName(session.email);
      setWho({ name, role: session.role, initials: displayInitials(session.email) });
    };
    apply();
    return subscribeSession(apply);
  }, []);

  const signOut = async () => {
    try {
      await api.logout();
    } catch {
      /* local session is cleared even if the server is unreachable */
    }
    window.location.assign('/login-screen');
  };

  const isActive = (href: string) => (href === '/' ? pathname === '/' : pathname.startsWith(href));

  const content = (isCollapsed: boolean) => (
    <div className="flex h-full flex-col bg-navy text-primary-foreground">
      <div
        className={`flex h-16 items-center gap-2 border-b border-navy-3 ${isCollapsed ? 'justify-center px-2' : 'px-4'}`}
      >
        <AppLogo size={36} />
        {!isCollapsed && (
          <div className="leading-tight">
            <span className="block text-sm font-semibold tracking-tight">InsightEngine</span>
            <span className="block text-[11px] text-cyan">Network observability</span>
          </div>
        )}
      </div>

      <nav className="scroll-thin flex-1 space-y-5 overflow-y-auto px-2 py-4" aria-label="Primary">
        {GROUPS.map((g) => (
          <div key={`grp-${g.title}`}>
            {!isCollapsed && (
              <p className="label-caps mb-1.5 px-3 text-[10px] text-down">{g.title}</p>
            )}
            <ul className="space-y-0.5">
              {g.items.map((item) => {
                const active = isActive(item.href);
                const badge = item.href === '/not-in-net-box' ? pending : item.badge;
                return (
                  <li key={`nav-${item.label}`} className="group relative">
                    <Link
                      href={item.href}
                      onClick={onCloseMobile}
                      aria-current={active ? 'page' : undefined}
                      className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-all duration-150 ${
                        active
                          ? 'bg-cyan/15 font-semibold text-cyan'
                          : 'text-primary-foreground/80 hover:bg-navy-3 hover:text-primary-foreground'
                      } ${isCollapsed ? 'justify-center' : ''}`}
                    >
                      <Icon name={item.icon} size={18} variant={active ? 'solid' : 'outline'} />
                      {!isCollapsed && <span className="flex-1 truncate">{item.label}</span>}
                      {!isCollapsed && badge ? (
                        <span className="rounded-full bg-warning px-1.5 py-0.5 text-[10px] font-bold tabular text-warning-foreground">
                          {badge}
                        </span>
                      ) : null}
                    </Link>
                    {isCollapsed && (
                      <span
                        role="tooltip"
                        className="pointer-events-none absolute left-full top-1/2 z-50 ml-2 -translate-y-1/2 whitespace-nowrap rounded-md bg-navy-3 px-2 py-1 text-xs text-primary-foreground opacity-0 shadow-pop transition-opacity group-hover:opacity-100"
                      >
                        {item.label}
                        {badge ? ` (${badge})` : ''}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-navy-3 p-2">
        <div
          className={`flex items-center gap-2 rounded-md bg-navy-2 p-2 ${isCollapsed ? 'justify-center' : ''}`}
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-teal text-xs font-bold text-accent-foreground">
            {who.initials}
          </span>
          {!isCollapsed && (
            <div className="min-w-0 flex-1 leading-tight">
              <p className="truncate text-sm font-medium">{who.name}</p>
              <p className="truncate text-[11px] text-down">{who.role}</p>
            </div>
          )}
          {!isCollapsed && (
            <button
              type="button"
              onClick={signOut}
              aria-label="Sign out"
              className="rounded-md p-1.5 text-down transition-colors hover:bg-navy-3 hover:text-primary-foreground"
            >
              <Icon name="ArrowRightOnRectangleIcon" size={16} />
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={onToggle}
          aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className="mt-2 hidden w-full items-center justify-center gap-2 rounded-md py-1.5 text-xs text-down transition-colors hover:bg-navy-3 hover:text-primary-foreground lg:flex"
        >
          <Icon name={isCollapsed ? 'ChevronDoubleRightIcon' : 'ChevronDoubleLeftIcon'} size={14} />
          {!isCollapsed && 'Collapse'}
        </button>
      </div>
    </div>
  );

  return (
    <>
      <aside
        className={`fixed inset-y-0 left-0 z-40 hidden border-r border-navy-3 transition-[width] duration-300 ease-in-out md:block ${
          collapsed ? 'w-16' : 'w-60'
        }`}
      >
        {content(collapsed)}
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div
            className="absolute inset-0 bg-navy/60 fade-in"
            onClick={onCloseMobile}
            aria-hidden="true"
          />
          <aside className="absolute inset-y-0 left-0 w-64 slide-in-right">{content(false)}</aside>
        </div>
      )}
    </>
  );
}

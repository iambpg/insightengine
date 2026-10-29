'use client';

import React, { useEffect, useState } from 'react';
import Icon from '@/components/ui/AppIcon';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import { isMockMode } from '@/lib/apiMode';
import { canSeeApplications } from '@/lib/settings/access';
import { useSession } from '@/lib/useSession';
import RolesTab from './RolesTab';
import DatabaseTab from './DatabaseTab';
import WebhookTab from './WebhookTab';
import ApplicationsPanel from './ApplicationsPanel';
import AppsLauncher from '@/components/AppsLauncher';
import SnmpTab from './SnmpTab';

type Tab = 'applications' | 'apps' | 'roles' | 'database' | 'webhook' | 'snmp';

const BASE_TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'apps', label: 'Apps', icon: 'Squares2X2Icon' },
  { key: 'roles', label: 'Roles and users', icon: 'UserGroupIcon' },
  { key: 'database', label: 'Database (read-only)', icon: 'CircleStackIcon' },
  { key: 'webhook', label: 'Alertmanager webhook', icon: 'BellAlertIcon' },
  { key: 'snmp', label: 'SNMP', icon: 'KeyIcon' },
];

export default function SettingsView() {
  const { role, ready } = useSession();
  const showApps = ready && canSeeApplications(role);
  const [tab, setTab] = useState<Tab>('roles');
  const [picked, setPicked] = useState(false);

  useEffect(() => {
    if (showApps && !picked) setTab('applications');
  }, [showApps, picked]);

  const tabs = showApps
    ? [
        { key: 'applications' as const, label: 'Applications', icon: 'Squares2X2Icon' },
        ...BASE_TABS,
      ]
    : BASE_TABS;

  return (
    <div className="space-y-5">
      <header className="px-4">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Application configuration, who can do what, what the platform stores, and how alerts reach
          InsightEngine.
        </p>
      </header>
      {isMockMode() ? <ExampleDataBanner /> : null}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[220px_1fr]">
        <div
          role="tablist"
          aria-label="Settings sections"
          aria-orientation="vertical"
          className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible"
        >
          {tabs.map((t) => {
            const on = tab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                id={`tab-${t.key}`}
                aria-selected={on}
                aria-controls={`panel-${t.key}`}
                onClick={() => {
                  setPicked(true);
                  setTab(t.key);
                }}
                className={`flex shrink-0 items-center gap-2.5 rounded-md px-3 py-2.5 text-left text-sm transition-all duration-150 active:scale-[0.98] ${
                  on
                    ? 'bg-navy font-semibold text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                }`}
              >
                <Icon
                  name={t.icon}
                  size={18}
                  variant={on ? 'solid' : 'outline'}
                  className={on ? 'text-cyan' : ''}
                />
                {t.label}
              </button>
            );
          })}
        </div>

        <div
          role="tabpanel"
          id={`panel-${tab}`}
          aria-labelledby={`tab-${tab}`}
          className="min-w-0 fade-in"
          key={tab}
        >
          {tab === 'applications' && showApps && <ApplicationsPanel role={role} />}
          {tab === 'apps' && <AppsLauncher layout="page" />}
          {tab === 'roles' && <RolesTab />}
          {tab === 'database' && <DatabaseTab />}
          {tab === 'webhook' && <WebhookTab />}
          {tab === 'snmp' && <SnmpTab />}
        </div>
      </div>
    </div>
  );
}

'use client';

import React from 'react';
import { toast } from 'sonner';
import Icon from '@/components/ui/AppIcon';

import type { DemoAccount } from '@/lib/mock/mockAuth';

export type { DemoAccount };

export default function CredentialsBox({
  accounts,
  onUse,
}: {
  accounts: DemoAccount[];
  onUse: (a: DemoAccount) => void;
}) {
  const copy = (text: string, what: string) => {
    navigator.clipboard?.writeText(text);
    toast.success(`${what} copied`);
  };
  return (
    <section
      className="mt-6 rounded-lg border border-accent/40 bg-accent/10 p-3"
      aria-labelledby="demo-title"
    >
      <h2 id="demo-title" className="flex items-center gap-2 text-xs font-semibold">
        <Icon name="BeakerIcon" size={14} /> Demo accounts{' '}
        <span className="font-normal text-muted-foreground">
          · example data, click a row to fill the form
        </span>
      </h2>
      <div className="mt-2 overflow-hidden rounded-md border border-border bg-card">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border bg-muted/60 text-left text-muted-foreground">
              <th scope="col" className="px-2.5 py-1.5 font-semibold">
                Role
              </th>
              <th scope="col" className="px-2.5 py-1.5 font-semibold">
                Email
              </th>
              <th scope="col" className="px-2.5 py-1.5 text-right font-semibold">
                <span className="sr-only">Use</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((a) => (
              <tr key={a.role} className="border-b border-border last:border-0 hover:bg-accent/10">
                <td className="px-2.5 py-1.5 font-medium">{a.role}</td>
                <td className="max-w-[170px] truncate px-2.5 py-1.5 font-mono-data" title={a.email}>
                  {a.email}
                </td>
                <td className="px-2.5 py-1.5">
                  <div className="flex items-center justify-end gap-1">
                    <button
                      type="button"
                      onClick={() => copy(a.password, 'Password')}
                      aria-label={`Copy ${a.role} password`}
                      className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    >
                      <Icon name="ClipboardDocumentIcon" size={13} />
                    </button>
                    <button
                      type="button"
                      onClick={() => onUse(a)}
                      className="rounded-md bg-primary px-2 py-0.5 text-[11px] font-semibold text-primary-foreground transition-all hover:opacity-90 active:scale-95"
                    >
                      Use
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

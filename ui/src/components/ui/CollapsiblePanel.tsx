'use client';

import React, { useId, useState } from 'react';
import Icon from '@/components/ui/AppIcon';

type Props = {
  title: string;
  titleId?: string;
  subtitle?: React.ReactNode;
  meta?: React.ReactNode;
  /** Extra controls rendered beside the toggle (not inside the button). */
  actions?: React.ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  className?: string;
  headerClassName?: string;
  bodyClassName?: string;
  headingLevel?: 'h2' | 'h3';
  children: React.ReactNode;
};

export default function CollapsiblePanel({
  title,
  titleId,
  subtitle,
  meta,
  actions,
  defaultOpen = true,
  open: controlledOpen,
  onOpenChange,
  className = 'rounded-none border-x-0 border-y border-border bg-card shadow-card',
  headerClassName = '',
  bodyClassName = '',
  headingLevel = 'h2',
  children,
}: Props) {
  const autoId = useId();
  const headingId = titleId ?? `panel-title-${autoId}`;
  const panelId = `panel-body-${autoId}`;
  const [uncontrolled, setUncontrolled] = useState(defaultOpen);
  const open = controlledOpen ?? uncontrolled;
  const setOpen = (next: boolean) => {
    onOpenChange?.(next);
    if (controlledOpen === undefined) setUncontrolled(next);
  };

  const Heading = headingLevel;

  return (
    <section className={className} aria-labelledby={headingId}>
      <div className={`flex flex-wrap items-center gap-2 border-b border-border ${headerClassName}`}>
        <Heading id={headingId} className={`min-w-0 flex-1 text-base font-semibold ${headingLevel === 'h3' ? 'text-sm' : ''}`}>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => setOpen(!open)}
            className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-left hover:bg-muted/60"
          >
            <Icon
              name="ChevronDownIcon"
              size={16}
              className={`shrink-0 text-muted-foreground transition-transform ${open ? 'rotate-0' : '-rotate-90'}`}
            />
            <span className="min-w-0 flex-1">
              <span className="block">{title}</span>
              {subtitle ? <span className="mt-0.5 block text-xs font-normal text-muted-foreground">{subtitle}</span> : null}
            </span>
            {meta}
          </button>
        </Heading>
        {actions ? <div className="flex flex-wrap items-center gap-2 px-4 py-2">{actions}</div> : null}
      </div>
      {open ? (
        <div id={panelId} role="region" aria-labelledby={headingId} className={bodyClassName}>
          {children}
        </div>
      ) : null}
    </section>
  );
}

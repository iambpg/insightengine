'use client';

import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import Link from 'next/link';
import Modal from '@/components/ui/Modal';

export interface InspectItem {
  title: string;
  detail?: string;
  meta?: string;
  href?: string;
}

type Tone = 'warning' | 'critical' | 'info' | 'success';

const TONE: Record<Tone, string> = {
  warning: 'text-foreground decoration-warning',
  critical: 'text-destructive decoration-destructive',
  info: 'text-foreground decoration-info',
  success: 'text-success decoration-success',
};

interface Props {
  label: string;
  title?: string;
  tone?: Tone;
  items: InspectItem[];
  total?: number;
  children?: React.ReactNode;
  className?: string;
  actionLabel?: string;
  onAction?: () => void;
}

/** Hover previews the rows. Click opens them in a centered panel. */
export default function InspectNote({ label, title, tone = 'warning', items, total, children, className = '', actionLabel, onAction }: Props) {
  const [open, setOpen] = useState(false);
  const [tip, setTip] = useState<{ x: number; y: number } | null>(null);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const heading = title || label;
  const preview = items.slice(0, 3);
  const count = total && total > items.length ? total : items.length;

  const place = (target: HTMLElement) => {
    const rect = target.getBoundingClientRect();
    setTip({ x: rect.left + rect.width / 2, y: rect.top });
  };

  return (
    <>
      <button
        type="button"
        className={children
          ? `inline-flex text-left ${className}`
          : `inline rounded-sm underline decoration-dotted underline-offset-4 hover:decoration-solid ${TONE[tone]} ${className}`}
        aria-label={label}
        onMouseEnter={(event) => place(event.currentTarget)}
        onMouseLeave={() => setTip(null)}
        onFocus={(event) => place(event.currentTarget)}
        onBlur={() => setTip(null)}
        onClick={() => {
          setTip(null);
          setOpen(true);
        }}
      >
        {children ?? label}
      </button>
      {tip && typeof document !== 'undefined' ? createPortal(
        <div
          role="tooltip"
          style={{ left: tip.x, top: tip.y - 8 }}
          className="pointer-events-none fixed z-[80] w-80 -translate-x-1/2 -translate-y-full rounded-lg border border-navy-3 bg-navy p-3 text-primary-foreground shadow-pop"
        >
          <p className="text-xs font-semibold">{heading}</p>
          {preview.length === 0 ? (
            <p className="mt-1 text-xs text-down">Nothing is listed for this.</p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {preview.map((item, index) => (
                <li key={`${item.title}-${index}`} className="text-xs">
                  <span className="font-medium">{item.title}</span>
                  {item.meta ? <span className="text-down"> · {item.meta}</span> : null}
                  {item.detail ? <span className="mt-0.5 block truncate text-down">{item.detail}</span> : null}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 border-t border-navy-3 pt-1.5 text-[10px] text-down">Click to open the full list</p>
        </div>,
        document.body,
      ) : null}
      {mounted ? createPortal(
      <Modal
        open={open}
        title={heading}
        description={count ? `${count} item${count === 1 ? '' : 's'}${total && total > items.length ? `, showing the latest ${items.length}` : ''}` : 'Nothing is listed for this.'}
        onClose={() => setOpen(false)}
        width="max-w-2xl"
        footer={actionLabel && onAction ? (
          <button
            type="button"
            onClick={() => {
              onAction();
              setOpen(false);
            }}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground"
          >
            {actionLabel}
          </button>
        ) : undefined}
      >
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing is listed for this.</p>
        ) : (
          <ul className="max-h-[60vh] space-y-2 overflow-y-auto pr-1">
            {items.map((item, index) => (
              <li key={`${item.title}-${item.meta || ''}-${index}`} className="rounded-md border border-border bg-background px-3 py-2">
                <div className="flex items-baseline justify-between gap-3">
                  {item.href ? (
                    <Link href={item.href} className="text-sm font-semibold hover:text-primary hover:underline" onClick={() => setOpen(false)}>
                      {item.title}
                    </Link>
                  ) : (
                    <p className="text-sm font-semibold">{item.title}</p>
                  )}
                  {item.meta ? <p className="shrink-0 font-mono-data text-[11px] text-muted-foreground">{item.meta}</p> : null}
                </div>
                {item.detail ? <p className="mt-1 text-sm leading-5 text-muted-foreground">{item.detail}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </Modal>,
      document.body,
      ) : null}
    </>
  );
}

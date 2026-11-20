'use client';

import React, { useEffect, useRef, useState } from 'react';
import Icon from '@/components/ui/AppIcon';
import { applyTheme, readTheme, THEMES, type ThemeId } from '@/lib/theme';

const SWATCH: Record<ThemeId, string> = {
  day: '#f5f8fc',
  night: '#0b1220',
  ocean: '#0c2a33',
  sand: '#f6f1e7',
};

export default function ThemeMenu() {
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeId>('day');
  const menuRef = useRef<HTMLDivElement>(null);
  const current = THEMES.find((item) => item.id === theme) ?? THEMES[0];

  useEffect(() => {
    const sync = () => setTheme(readTheme());
    sync();
    window.addEventListener('ie-theme', sync);
    return () => window.removeEventListener('ie-theme', sync);
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Theme, ${current.label}`}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1.5 text-sm font-medium text-foreground hover:bg-muted"
      >
        <span className="h-3.5 w-3.5 rounded-full border border-border" style={{ background: SWATCH[theme] }} />
        <Icon name="SwatchIcon" size={16} />
        <span className="hidden sm:inline">{current.label}</span>
      </button>
      {open ? (
        <div role="menu" aria-label="Themes" className="absolute right-0 top-full z-50 mt-2 w-44 rounded-lg border border-border bg-card p-1 shadow-pop">
          {THEMES.map((item) => (
            <button
              key={item.id}
              type="button"
              role="menuitemradio"
              aria-checked={item.id === theme}
              onClick={() => {
                applyTheme(item.id);
                setTheme(item.id);
                setOpen(false);
              }}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-foreground hover:bg-muted"
            >
              <span className="h-4 w-4 rounded-full border border-border" style={{ background: SWATCH[item.id] }} />
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

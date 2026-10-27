'use client';

import React from 'react';
import type { DiffResult } from '@/lib/contract';
import { sideBySide } from '@/lib/settings/diff';

export default function DiffBlock({
  diff,
  mode,
  onMode,
}: {
  diff: DiffResult;
  mode: 'unified' | 'side';
  onMode: (mode: 'unified' | 'side') => void;
}) {
  const rows = sideBySide(diff.unified);
  return (
    <section
      aria-label="Diff against saved version"
      className="overflow-hidden rounded-md border border-border bg-card"
    >
      <header className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2 text-xs">
        <span className="font-semibold text-success">+{diff.added}</span>
        <span className="font-semibold text-destructive">-{diff.removed}</span>
        <span className="text-muted-foreground">against the saved version</span>
        <div className="ml-auto flex rounded-md border border-border p-0.5">
          <button
            type="button"
            onClick={() => onMode('unified')}
            className={`rounded px-2 py-0.5 ${mode === 'unified' ? 'bg-navy text-primary-foreground' : ''}`}
          >
            Unified
          </button>
          <button
            type="button"
            onClick={() => onMode('side')}
            className={`rounded px-2 py-0.5 ${mode === 'side' ? 'bg-navy text-primary-foreground' : ''}`}
          >
            Side by side
          </button>
        </div>
      </header>
      {mode === 'unified' ? (
        <pre className="scroll-thin max-h-72 overflow-auto p-3 font-mono-data text-xs leading-5">
          {diff.unified.split('\n').map((line, index) => {
            const tone =
              line.startsWith('+') && !line.startsWith('+++')
                ? 'text-success'
                : line.startsWith('-') && !line.startsWith('---')
                  ? 'text-destructive'
                  : line.startsWith('@@')
                    ? 'text-info'
                    : 'text-muted-foreground';
            return (
              <div key={`u-${index}`} className={tone}>
                {line || ' '}
              </div>
            );
          })}
        </pre>
      ) : (
        <div className="scroll-thin max-h-72 overflow-auto">
          <table className="w-full font-mono-data text-xs">
            <tbody>
              {rows.map((row, index) => (
                <tr key={`s-${index}`} className="align-top">
                  <td
                    className={`w-1/2 whitespace-pre-wrap border-r border-border px-2 py-0.5 ${row.tone === 'del' || row.tone === 'both' ? 'bg-destructive/10' : ''}`}
                  >
                    {row.left || ' '}
                  </td>
                  <td
                    className={`w-1/2 whitespace-pre-wrap px-2 py-0.5 ${row.tone === 'add' || row.tone === 'both' ? 'bg-success/10' : ''}`}
                  >
                    {row.right || ' '}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

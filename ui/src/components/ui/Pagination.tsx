'use client';

import React from 'react';
import Icon from '@/components/ui/AppIcon';

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
  onPageSize: (n: number) => void;
  sizes?: number[];
  noun?: string;
}

export default function Pagination({ page, pageSize, total, onPage, onPageSize, sizes = [10, 25, 50, 100], noun = 'items' }: PaginationProps) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);

  const nums: (number | string)[] = [];
  const add = (v: number | string) => nums.push(v);
  if (pages <= 7) {
    for (let i = 1; i <= pages; i++) add(i);
  } else {
    add(1);
    if (page > 3) add('gap-l');
    for (let i = Math.max(2, page - 1); i <= Math.min(pages - 1, page + 1); i++) add(i);
    if (page < pages - 2) add('gap-r');
    add(pages);
  }

  return (
    <div className="flex flex-col gap-3 border-t border-border px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3 text-muted-foreground">
        <span className="tabular">
          <span className="font-medium text-foreground">{from.toLocaleString('en-US')}</span>–
          <span className="font-medium text-foreground">{to.toLocaleString('en-US')}</span> of{' '}
          <span className="font-medium text-foreground">{total.toLocaleString('en-US')}</span> {noun}
        </span>
        <label className="flex items-center gap-1.5">
          <span className="sr-only">Rows per page</span>
          <select
            value={pageSize}
            onChange={(e) => onPageSize(Number(e.target.value))}
            className="rounded-md border border-input bg-card px-2 py-1 text-sm text-foreground"
          >
            {sizes.map((s) => (
              <option key={`size-${s}`} value={s}>
                {s} / page
              </option>
            ))}
          </select>
        </label>
      </div>
      <nav aria-label="Pagination" className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => onPage(Math.max(1, page - 1))}
          disabled={page === 1}
          aria-label="Previous page"
          className="rounded-md border border-border p-1.5 text-muted-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Icon name="ChevronLeftIcon" size={16} />
        </button>
        {nums.map((n) =>
          typeof n === 'string' ? (
            <span key={`pg-${n}`} className="px-1.5 text-muted-foreground">
              …
            </span>
          ) : (
            <button
              key={`pg-${n}`}
              type="button"
              onClick={() => onPage(n)}
              aria-current={n === page ? 'page' : undefined}
              className={`min-w-8 rounded-md px-2 py-1 text-sm tabular transition-colors ${
                n === page ? 'bg-navy text-primary-foreground font-semibold' : 'text-muted-foreground hover:bg-muted'
              }`}
            >
              {n}
            </button>
          )
        )}
        <button
          type="button"
          onClick={() => onPage(Math.min(pages, page + 1))}
          disabled={page === pages}
          aria-label="Next page"
          className="rounded-md border border-border p-1.5 text-muted-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Icon name="ChevronRightIcon" size={16} />
        </button>
      </nav>
    </div>
  );
}
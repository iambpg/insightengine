import type { DiffResult } from '@/lib/contract';

export interface SideRow {
  left: string;
  right: string;
  tone: 'ctx' | 'add' | 'del' | 'both';
}

export function unifiedDiff(before: string, after: string, filename: string): DiffResult {
  const a = before.split('\n');
  const b = after.split('\n');
  const ops = a.length * b.length > 1_500_000 ? coarseOps(a, b) : lcsOps(a, b);
  const body: string[] = [`--- a/${filename}`, `+++ b/${filename}`];
  let added = 0;
  let removed = 0;
  let i = 0;
  while (i < ops.length) {
    const start = i;
    while (i < ops.length && ops[i].kind === 'ctx') i += 1;
    const changeStart = i;
    while (i < ops.length && ops[i].kind !== 'ctx') i += 1;
    if (changeStart === i) break;
    const from = Math.max(0, changeStart - 3);
    const to = Math.min(ops.length, i + 3);
    const oldStart = ops[from].oldNo ?? ops[changeStart].oldNo ?? 1;
    const newStart = ops[from].newNo ?? ops[changeStart].newNo ?? 1;
    let oldCount = 0;
    let newCount = 0;
    const hunk: string[] = [];
    for (let k = from; k < to; k += 1) {
      const op = ops[k];
      if (op.kind === 'ctx') {
        hunk.push(` ${op.text}`);
        oldCount += 1;
        newCount += 1;
      } else if (op.kind === 'del') {
        hunk.push(`-${op.text}`);
        oldCount += 1;
        removed += 1;
      } else {
        hunk.push(`+${op.text}`);
        newCount += 1;
        added += 1;
      }
    }
    // Count only the lines we will emit. Context outside the window was skipped.
    void start;
    body.push(`@@ -${oldStart},${oldCount} +${newStart},${newCount} @@`);
    body.push(...hunk);
    while (i < ops.length && ops[i].kind === 'ctx') i += 1;
  }
  if (added === 0 && removed === 0) {
    body.push('@@ -1,0 +1,0 @@');
  }
  return { unified: body.join('\n'), added, removed };
}

interface Op {
  kind: 'ctx' | 'add' | 'del';
  text: string;
  oldNo?: number;
  newNo?: number;
}

function lcsOps(a: string[], b: string[]): Op[] {
  const n = a.length;
  const m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const ops: Op[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ops.push({ kind: 'ctx', text: a[i], oldNo: i + 1, newNo: j + 1 });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ kind: 'del', text: a[i], oldNo: i + 1 });
      i += 1;
    } else {
      ops.push({ kind: 'add', text: b[j], newNo: j + 1 });
      j += 1;
    }
  }
  while (i < n) {
    ops.push({ kind: 'del', text: a[i], oldNo: i + 1 });
    i += 1;
  }
  while (j < m) {
    ops.push({ kind: 'add', text: b[j], newNo: j + 1 });
    j += 1;
  }
  return ops;
}

function coarseOps(a: string[], b: string[]): Op[] {
  let prefix = 0;
  while (prefix < a.length && prefix < b.length && a[prefix] === b[prefix]) prefix += 1;
  let suffix = 0;
  while (
    suffix < a.length - prefix &&
    suffix < b.length - prefix &&
    a[a.length - 1 - suffix] === b[b.length - 1 - suffix]
  ) {
    suffix += 1;
  }
  const ops: Op[] = [];
  for (let i = 0; i < prefix; i += 1)
    ops.push({ kind: 'ctx', text: a[i], oldNo: i + 1, newNo: i + 1 });
  for (let i = prefix; i < a.length - suffix; i += 1)
    ops.push({ kind: 'del', text: a[i], oldNo: i + 1 });
  for (let j = prefix; j < b.length - suffix; j += 1)
    ops.push({ kind: 'add', text: b[j], newNo: j + 1 });
  for (let s = 0; s < suffix; s += 1) {
    const i = a.length - suffix + s;
    const j = b.length - suffix + s;
    ops.push({ kind: 'ctx', text: a[i], oldNo: i + 1, newNo: j + 1 });
  }
  return ops;
}

export function sideBySide(unified: string): SideRow[] {
  const rows: SideRow[] = [];
  const pending: string[] = [];
  const flush = () => {
    while (pending.length) rows.push({ left: pending.shift() ?? '', right: '', tone: 'del' });
  };
  for (const line of unified.split('\n')) {
    if (
      line.startsWith('+++') ||
      line.startsWith('---') ||
      line.startsWith('@@') ||
      line.startsWith('diff')
    ) {
      continue;
    }
    if (line.startsWith('-')) {
      pending.push(line.slice(1));
      continue;
    }
    if (line.startsWith('+')) {
      const left = pending.shift();
      rows.push(
        left !== undefined
          ? { left, right: line.slice(1), tone: 'both' }
          : { left: '', right: line.slice(1), tone: 'add' }
      );
      continue;
    }
    if (line.startsWith('\\')) continue;
    flush();
    const text = line.startsWith(' ') ? line.slice(1) : line;
    rows.push({ left: text, right: text, tone: 'ctx' });
  }
  flush();
  return rows;
}

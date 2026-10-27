import { describe, expect, it } from 'vitest';
import { sideBySide, unifiedDiff } from '@/lib/settings/diff';
import { rangeHitsSecret } from '@/lib/settings/secrets';

describe('unifiedDiff', () => {
  it('counts a single added line', () => {
    const diff = unifiedDiff('a\nb\n', 'a\nb\nc\n', 'file.txt');
    expect(diff.added).toBeGreaterThan(0);
    expect(diff.unified).toContain('+c');
    const rows = sideBySide(diff.unified);
    expect(rows.some((row) => row.right === 'c')).toBe(true);
  });
});

describe('secrets', () => {
  it('treats a masked token as locked', () => {
    const text = 'password: __SECRET__:snmp_v3_auth\n';
    const start = text.indexOf('__SECRET__');
    expect(rangeHitsSecret(text, start, start + 4)).toBe(true);
    expect(rangeHitsSecret(text, 0, 4)).toBe(false);
  });
});

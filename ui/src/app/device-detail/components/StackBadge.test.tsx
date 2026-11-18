import React from 'react';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { StackMemberInfo } from '@/lib/types';
import StackBadge, { memberTooltip, stackMembersFor, tileMetrics } from './StackBadge';

function member(number: number, master = false, extra: Partial<StackMemberInfo> = {}): StackMemberInfo {
  return {
    number,
    role: master ? 'active' : 'member',
    model: `C9300-${number}`,
    serial: `SER${String(number).padStart(2, '0')}`,
    state: master ? 'ready' : '',
    master,
    ...extra,
  };
}

function stack(count: number, masterNumber: number, extra?: (number: number) => Partial<StackMemberInfo>): StackMemberInfo[] {
  return Array.from({ length: count }, (_, index) => {
    const number = index + 1;
    return member(number, number === masterNumber, extra ? extra(number) : {});
  });
}

function widthOf(label: string): number {
  return parseFloat(screen.getByRole('img', { name: new RegExp(`Member ${label}\\b`) }).style.width);
}

describe('stack badge', () => {
  it('shows one tile for a standalone switch', () => {
    render(<StackBadge members={stack(1, 1)} />);
    const tile = screen.getByRole('img', { name: /Member 01/ });
    expect(tile).toHaveTextContent('01');
    expect(tile).toHaveAttribute('data-master', 'true');
    expect(tile).toHaveAttribute('data-tone', 'teal');
    expect(screen.getAllByRole('img')).toHaveLength(1);
    expect(memberTooltip(stack(1, 1)[0])).toBe('Member 01 · active · C9300-1 · SER01 · ready');
  });

  it('draws member 01 larger when it is the master of a stack of two', () => {
    render(<StackBadge members={stack(2, 1)} />);
    expect(screen.getByRole('img', { name: /Member 01/ })).toHaveTextContent('01');
    expect(screen.getByRole('img', { name: /Member 02/ })).toHaveTextContent('02');
    expect(screen.getByTestId('stack-member-01')).toHaveAttribute('data-master', 'true');
    expect(screen.getByTestId('stack-member-02')).toHaveAttribute('data-master', 'false');
    expect(widthOf('01') / widthOf('02')).toBeCloseTo(1.4, 1);
    expect(Number(screen.getByTestId('stack-member-01').style.zIndex)).toBeGreaterThan(
      Number(screen.getByTestId('stack-member-02').style.zIndex),
    );
    expect(screen.getByTestId('stack-member-02')).toHaveAttribute('data-tone', 'amber');
  });

  it('draws member 02 larger when it is the master of a stack of two', () => {
    render(<StackBadge members={stack(2, 2)} />);
    expect(screen.getByTestId('stack-member-02')).toHaveAttribute('data-master', 'true');
    expect(screen.getByTestId('stack-member-01')).toHaveAttribute('data-master', 'false');
    expect(widthOf('02') / widthOf('01')).toBeCloseTo(1.4, 1);
    expect(Number(screen.getByTestId('stack-member-02').style.zIndex)).toBeGreaterThan(
      Number(screen.getByTestId('stack-member-01').style.zIndex),
    );
  });

  it('fits a stack of eight with member 05 on top', () => {
    render(<StackBadge members={stack(8, 5)} />);
    expect(screen.getAllByRole('img')).toHaveLength(8);
    for (let number = 1; number <= 8; number += 1) {
      const label = String(number).padStart(2, '0');
      expect(screen.getByTestId(`stack-member-${label}`)).toHaveTextContent(label);
    }
    expect(screen.getByTestId('stack-member-05')).toHaveAttribute('data-master', 'true');
    expect(screen.getByTestId('stack-member-05')).toHaveAttribute('data-tone', 'blue');
    expect(screen.getByTestId('stack-badge').style.gridTemplateColumns).toContain('repeat(4');
    const pair = tileMetrics(2);
    const eight = tileMetrics(8);
    expect(eight.base).toBeLessThan(pair.base);
    expect(eight.big / eight.base).toBeCloseTo(1.4, 1);
    expect(widthOf('05') / widthOf('01')).toBeCloseTo(1.4, 1);
  });

  it('shows tile 01 when a switch has no stack data', () => {
    const members = stackMembersFor({
      role: 'Access switch',
      modelFamily: 'C9300-48P',
      faceplate: { form_factor: 'access-switch-48' },
    });
    expect(members).toEqual([
      { number: 1, role: 'active', model: 'C9300-48P', serial: '', state: '', master: true },
    ]);
    render(<StackBadge members={members || []} />);
    expect(screen.getByRole('img', { name: /Member 01/ })).toHaveTextContent('01');
    expect(screen.getAllByRole('img')).toHaveLength(1);
  });

  it('gives a standby member a ring and hides the badge on other devices', () => {
    render(<StackBadge members={[member(1, true), member(2, false, { role: 'standby' })]} />);
    expect(screen.getByTestId('stack-member-02').style.boxShadow).toContain('0 0 0 1.5px');
    expect(screen.getByRole('img', { name: /Member 02 · standby/ })).toBeInTheDocument();
    expect(stackMembersFor({ role: 'Firewall', faceplate: { form_factor: 'firewall' } })).toBeNull();
    expect(stackMembersFor({ role: 'Wireless controller', faceplate: { form_factor: 'wireless-controller' } })).toBeNull();
  });
});

describe('stack badge screenshots', () => {
  it('writes one frame per case when IE_STACK_SHOTS is set', () => {
    if (process.env.IE_STACK_SHOTS !== '1') return;
    const cases: Array<[string, StackMemberInfo[] | null]> = [
      ['standalone', stack(1, 1)],
      ['stack-2-master-1', stack(2, 1)],
      ['stack-2-master-2', stack(2, 2)],
      ['stack-8-master-5', stack(8, 5)],
      ['no-data', stackMembersFor({ role: 'Access switch', modelFamily: 'C9300-48P', faceplate: { form_factor: 'access-switch-48' } })],
    ];
    const dir = process.env.IE_STACK_SHOT_DIR || path.join(os.tmpdir(), 'stack-badge-shots');
    fs.mkdirSync(dir, { recursive: true });
    for (const [name, members] of cases) {
      const { container, unmount } = render(
        <div style={{ width: 360, height: 140, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', background: '#f8fafc', padding: 12, boxSizing: 'border-box' }}>
          <div style={{ display: 'flex', height: 86, width: 280, alignItems: 'center', gap: 6, border: '1px solid #e2e8f0', background: '#ffffff', padding: 4, boxSizing: 'border-box' }}>
            <StackBadge members={members || []} />
            <div style={{ flex: 1, height: '100%', display: 'grid', gridTemplateColumns: '1fr 1fr', gridTemplateRows: '40px 40px', gap: 6 }}>
              {['Rediscover', 'Netbox Sync', 'Re-run health check', 'Open device'].map((label) => (
                <div key={label} style={{ border: '1px solid #cbd5e1', borderRadius: 6, font: '600 11px/1.1 ui-sans-serif, system-ui', display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', padding: 2 }}>
                  {label}
                </div>
              ))}
            </div>
          </div>
        </div>,
      );
      const html = `<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0">${container.innerHTML}</body></html>`;
      fs.writeFileSync(path.join(dir, `${name}.html`), html);
      unmount();
    }
  });
});

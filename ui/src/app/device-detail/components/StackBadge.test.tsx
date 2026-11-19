import React from 'react';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { StackMemberInfo } from '@/lib/types';
import StackBadge, { memberTooltip, stackMembersFor, tileHealth, tileMetrics } from './StackBadge';

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
    expect(tile).toHaveAttribute('data-tone', 'green');
    expect(tile).toHaveAttribute('data-health', 'healthy');
    expect(tile).toHaveAttribute('title', expect.stringContaining('Member state is ready'));
    expect(screen.getAllByRole('img')).toHaveLength(1);
    expect(memberTooltip(stack(1, 1)[0])).toBe('Member 01 · active · C9300-1 · SER01 · ready');
  });

  it('draws member 01 larger when it is the master of a stack of two', () => {
    render(<StackBadge members={stack(2, 1)} />);
    expect(screen.getByRole('img', { name: /Member 01/ })).toHaveTextContent('01');
    expect(screen.getByRole('img', { name: /Member 02/ })).toHaveTextContent('02');
    expect(screen.getByTestId('stack-member-01')).toHaveAttribute('data-master', 'true');
    expect(screen.getByTestId('stack-member-02')).toHaveAttribute('data-master', 'false');
    expect(widthOf('01') / widthOf('02')).toBeCloseTo(1.3, 1);
    expect(screen.getByTestId('stack-member-01').style.fontSize).toBe('12px');
    expect(screen.getByTestId('stack-member-01').style.fontWeight).toBe('600');
    expect(screen.getByTestId('stack-member-01').style.borderRadius).toBe('40%');
    expect(Number(screen.getByTestId('stack-member-01').style.zIndex)).toBeGreaterThan(
      Number(screen.getByTestId('stack-member-02').style.zIndex),
    );
    expect(screen.getByTestId('stack-member-02')).toHaveAttribute('data-tone', 'grey');
    expect(screen.getByTestId('stack-member-02')).toHaveAttribute('data-health', 'unknown');
    expect(screen.getByTestId('stack-member-02')).toHaveAttribute('title', expect.stringContaining('No data pulled from this member'));
  });

  it('draws member 02 larger when it is the master of a stack of two', () => {
    render(<StackBadge members={stack(2, 2)} />);
    expect(screen.getByTestId('stack-member-02')).toHaveAttribute('data-master', 'true');
    expect(screen.getByTestId('stack-member-01')).toHaveAttribute('data-master', 'false');
    expect(widthOf('02') / widthOf('01')).toBeCloseTo(1.3, 1);
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
    expect(screen.getByTestId('stack-member-05')).toHaveAttribute('data-tone', 'green');
    expect(screen.getByTestId('stack-member-05')).toHaveAttribute('data-health', 'healthy');
    expect(screen.getByTestId('stack-badge').style.gridTemplateColumns).toContain('repeat(4');
    const pair = tileMetrics(2);
    const eight = tileMetrics(8);
    expect(pair.base).toBe(26);
    expect(eight.base).toBe(26);
    expect(pair.gap).toBe(4);
    expect(eight.big / eight.base).toBeCloseTo(1.3, 1);
    expect(pair.font).toBe(12);
    expect(widthOf('05') / widthOf('01')).toBeCloseTo(1.3, 1);
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

  it('colours a member that is not ready red, and uses device health when no member was checked', () => {
    render(<StackBadge members={[member(1, true, { state: 'verMismatch' }), member(2, false, { state: 'ready' })]} />);
    expect(screen.getByTestId('stack-member-01')).toHaveAttribute('data-health', 'critical');
    expect(screen.getByTestId('stack-member-01')).toHaveAttribute('data-tone', 'red');
    expect(screen.getByTestId('stack-member-01')).toHaveStyle({ color: '#fffef8' });
    expect(screen.getByTestId('stack-member-02')).toHaveAttribute('data-health', 'healthy');
    const blank = stackMembersFor({ role: 'Access switch', faceplate: { form_factor: 'access-switch-48' } }) || [];
    expect(tileHealth(blank[0], blank, 'warning', 'CPU high. CPU is above the 80% threshold.')).toEqual({
      health: 'warning',
      reason: 'CPU high. CPU is above the 80% threshold.',
    });
  });

  it('keeps an explicit per-member health and shows it in the tooltip', () => {
    const members = [
      member(1, true, { health: 'healthy', healthReason: 'Member state is ready' }),
      member(2, false, { health: 'warning', healthReason: 'CPU high. CPU is above the 80% threshold.' }),
      member(3, false, { health: 'critical', healthReason: 'Fan degraded. Fan 1 state is critical.' }),
      member(4, false, { health: 'unknown', healthReason: 'No data pulled from this member' }),
    ];
    render(<StackBadge members={members} deviceHealth="critical" />);
    expect(screen.getByTestId('stack-member-02')).toHaveAttribute('data-health', 'warning');
    expect(screen.getByTestId('stack-member-02')).toHaveAttribute('data-tone', 'amber');
    expect(screen.getByTestId('stack-member-03')).toHaveAttribute('data-health', 'critical');
    expect(screen.getByTestId('stack-member-04')).toHaveAttribute('data-health', 'unknown');
    expect(screen.getByTestId('stack-member-04')).toHaveAttribute('data-tone', 'grey');
    expect(screen.getByRole('img', { name: /CPU is above the 80% threshold/ })).toBeInTheDocument();
    expect(widthOf('01') / widthOf('02')).toBeCloseTo(1.3, 1);
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
    const painted = (health: StackMemberInfo['health'], reason: string) => (number: number) => ({ health, healthReason: reason });
    const cases: Array<[string, StackMemberInfo[] | null]> = [
      ['healthy', stack(2, 1, painted('healthy', 'Member state is ready'))],
      ['warning', stack(2, 1, (number) => ({ health: number === 2 ? 'warning' : 'healthy', healthReason: number === 2 ? 'CPU high. CPU is above the 80% threshold.' : 'Member state is ready' }))],
      ['critical', stack(2, 1, painted('critical', 'Member state is verMismatch'))],
      ['unknown', stack(2, 1, painted('unknown', 'No data pulled from this member'))],
      ['stack-4-one-red', stack(4, 1, (number) => ({ health: number === 3 ? 'critical' : 'healthy', healthReason: number === 3 ? 'Fan degraded. Fan 1 state is critical.' : 'Member state is ready' }))],
      ['standalone', stack(1, 1)],
      ['stack-2-master-1', stack(2, 1)],
      ['stack-2-master-2', stack(2, 2)],
      ['stack-8-master-5', stack(8, 5, painted('healthy', 'Member state is ready'))],
      ['no-data', stackMembersFor({ role: 'Access switch', modelFamily: 'C9300-48P', faceplate: { form_factor: 'access-switch-48' } })],
    ];
    const dir = process.env.IE_STACK_SHOT_DIR || path.join(os.tmpdir(), 'stack-badge-shots');
    fs.mkdirSync(dir, { recursive: true });
    for (const [name, members] of cases) {
      const { container, unmount } = render(
        <div style={{ width: 980, height: 168, display: 'flex', alignItems: 'center', background: '#f8fafc', padding: 12, boxSizing: 'border-box' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, width: '100%' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 124px)', gap: 6 }}>
              {['Role', 'Model', 'Serial number', 'Site', 'Management IP', 'Uptime', 'Last poll', 'Firmware'].map((label) => (
                <div key={label} style={{ width: 124, height: 40, border: '1px solid #e2e8f0', borderRadius: 6, background: '#f8fafc', padding: '4px 6px', boxSizing: 'border-box', font: '600 9px/1.2 ui-sans-serif, system-ui', color: '#64748b' }}>
                  {label}
                  <div style={{ font: '600 11px/1.2 ui-sans-serif, system-ui', color: '#0f172a' }}>sample</div>
                </div>
              ))}
            </div>
            <div style={{ flex: 1 }} />
            <div style={{ display: 'flex', height: 86, alignItems: 'center', gap: 6, flexShrink: 0 }}>
              <StackBadge members={members || []} />
              <div style={{ height: '100%', width: 136, display: 'flex', flexDirection: 'column', gap: 2 }}>
                {['Rediscover', 'Re-run health check', 'NetBox Sync', 'Open device'].map((label) => (
                  <div key={label} style={{ flex: 1, border: '1px solid #cbd5e1', borderRadius: 6, font: '600 10px/1 ui-sans-serif, system-ui', display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', padding: 2 }}>
                    {label}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>,
      );
      const html = `<!doctype html><html><head><meta charset="utf-8"><style>
        [data-tone="green"]{background-color:#22c55e;background-image:linear-gradient(180deg,rgba(255,255,255,.75) 0%,rgba(255,255,255,0) 32%),linear-gradient(180deg,#dcfce7 0%,#22c55e 48%,#15803d 100%)}
        [data-tone="amber"]{background-color:#f59e0b;background-image:linear-gradient(180deg,rgba(255,255,255,.75) 0%,rgba(255,255,255,0) 32%),linear-gradient(180deg,#fef3c7 0%,#f59e0b 48%,#b45309 100%)}
        [data-tone="red"]{background-color:#ef4444;background-image:linear-gradient(180deg,rgba(255,255,255,.75) 0%,rgba(255,255,255,0) 32%),linear-gradient(180deg,#fecaca 0%,#ef4444 48%,#991b1b 100%)}
        [data-tone="grey"]{background-color:#94a3b8;background-image:linear-gradient(180deg,rgba(255,255,255,.75) 0%,rgba(255,255,255,0) 32%),linear-gradient(180deg,#f8fafc 0%,#94a3b8 48%,#64748b 100%)}
      </style></head><body style="margin:0">${container.innerHTML}</body></html>`;
      fs.writeFileSync(path.join(dir, `${name}.html`), html);
      unmount();
    }
  });
});

import React from 'react';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { FaceplateDevice, StackMember } from '@/lib/types';
import { buildFaceplateFor } from '@/lib/mockData';
import Faceplate from './Faceplate';

function renumber(device: FaceplateDevice, member: number): StackMember['ports'] {
  return (device.ports || []).map((port) => ({
    ...port,
    id: `${member}-${port.id}`,
    name: port.name.replace(/^(.*?)(\d+)/, (_match, prefix) => `${prefix}${member}`),
  }));
}

function stack(count: number): FaceplateDevice {
  const sample = buildFaceplateFor('access-switch-24');
  const health = (index: number): StackMember['health'] => (index === count - 1 && count > 2 ? 'fault' : index === 1 ? 'warning' : 'healthy');
  return {
    form_factor: 'switch-stack',
    role: 'Switch stack',
    members: Array.from({ length: count }, (_, index) => ({
      id: `m${index + 1}`,
      number: index + 1,
      health: health(index),
      note: '',
      ports: renumber(sample, index + 1),
    })),
  };
}

function frame(device: FaceplateDevice, parent: string | null) {
  return (
    <div style={{ position: 'relative', display: 'flex', alignItems: 'stretch', width: 1100, height: 168, background: '#f8fafc', boxSizing: 'border-box', padding: 6 }}>
      <div style={{ flex: 1, minWidth: 0, height: '100%' }}>
        <Faceplate device={device} caption={false} health={parent ? 'healthy' : 'unknown'} chassisLabel={device.form_factor === 'access-switch-48' ? 'C9300-48P' : 'C9300-24P'} />
      </div>
      <div style={{ width: 1, background: '#e2e8f0', margin: '0 8px' }} />
      <aside style={{ width: 168, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        <div style={{ font: '600 10px/1.2 ui-sans-serif, system-ui', letterSpacing: '0.08em', color: '#64748b', textTransform: 'uppercase' }}>Parent Device</div>
        {parent ? (
          <>
            <div style={{ marginTop: 6, font: '600 14px/1.2 ui-monospace, monospace', color: '#0f172a' }}>{parent}</div>
            <div style={{ marginTop: 8, width: 40, height: 22, border: '1px solid #94a3b8', borderRadius: 3, background: '#1e293b' }} />
            <div style={{ marginTop: 4, font: '500 10px/1 ui-monospace, monospace', color: '#64748b' }}>Te1/0/13</div>
          </>
        ) : (
          <div style={{ marginTop: 6, font: '500 14px/1.3 ui-sans-serif, system-ui', color: '#64748b' }}>No parent detected</div>
        )}
      </aside>
      {parent ? (
        <svg style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }} viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <path d="M 62 74 V 96 H 88 V 62" fill="none" stroke="#3b82f6" strokeWidth="1.6" />
        </svg>
      ) : null}
    </div>
  );
}

describe('faceplate screenshots', () => {
  it('writes the panel frames when IE_FACEPLATE_SHOTS is set', () => {
    if (process.env.IE_FACEPLATE_SHOTS !== '1') return;
    const cases: Array<[string, FaceplateDevice, string | null]> = [
      ['24-port', buildFaceplateFor('access-switch-24'), 'dist-sw-02'],
      ['48-port', buildFaceplateFor('access-switch-48'), 'dist-sw-02'],
      ['stack-2', stack(2), 'dist-sw-02'],
      ['stack-4', stack(4), 'dist-sw-02'],
      ['no-parent', buildFaceplateFor('access-switch-24'), null],
    ];
    const dir = process.env.IE_FACEPLATE_SHOT_DIR || path.join(os.tmpdir(), 'faceplate-shots');
    fs.mkdirSync(dir, { recursive: true });
    for (const [name, device, parent] of cases) {
      const { container, unmount } = render(frame(device, parent));
      const html = `<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0">${container.innerHTML}</body></html>`;
      fs.writeFileSync(path.join(dir, `${name}.html`), html);
      unmount();
    }
    expect(fs.existsSync(path.join(dir, 'no-parent.html'))).toBe(true);
  });
});

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
    <div
      data-faceplate-panel=""
      data-uplink={parent ? 'Te1/1/1' : ''}
      data-parent-port={parent ? 'Te1/0/13' : ''}
      style={{ position: 'relative', display: 'flex', alignItems: 'stretch', width: 1200, height: 168, background: '#f8fafc', boxSizing: 'border-box', padding: 4, overflow: 'hidden' }}
    >
      <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'flex-start' }}>
        <Faceplate device={device} caption={false} health={parent ? 'healthy' : 'unknown'} chassisLabel={device.form_factor === 'access-switch-48' ? 'C9300-48P' : 'C9300-24P'} />
      </div>
      <div style={{ width: 1, background: '#e2e8f0', margin: '0 8px' }} />
      <aside style={{ width: 176, display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '4px 8px' }}>
        <div style={{ font: '600 10px/1.2 ui-sans-serif, system-ui', letterSpacing: '0.08em', color: '#64748b', textTransform: 'uppercase' }}>Parent Device</div>
        {parent ? (
          <>
            <div style={{ marginTop: 6, font: '600 14px/1.2 ui-monospace, monospace', color: '#0f172a' }}>{parent}</div>
            <div data-port-name="Te1/0/13" style={{ marginTop: 8, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <div style={{ width: 56, height: 32, border: '1px solid #94a3b8', borderRadius: 3, background: '#1e293b', boxSizing: 'border-box' }} />
              <div style={{ marginTop: 4, font: '500 11px/1.2 ui-monospace, monospace', color: '#0f172a' }}>Te1/0/13</div>
            </div>
          </>
        ) : (
          <div style={{ marginTop: 6, font: '500 14px/1.3 ui-sans-serif, system-ui', color: '#64748b' }}>No parent detected</div>
        )}
      </aside>
    </div>
  );
}

const SHOT_CSS = `:root{--navy:#0b1220;--metal-1:#2a3140;--metal-2:#1b212d;--metal-3:#12161f;--metal-hi:#4a5468;--down:#d5deea;--font-mono:ui-monospace,monospace;--success:#17a672;--warning:#e8a317;--destructive:#d93a46;--cyan:#36cfff}`;

const CABLE_SCRIPT = `<script>
(function () {
  var panel = document.querySelector('[data-faceplate-panel]');
  if (!panel) return;
  var uplink = panel.getAttribute('data-uplink');
  var parentPort = panel.getAttribute('data-parent-port');
  if (!uplink || !parentPort) return;
  var local = panel.querySelector('[data-port-name="' + uplink + '"]');
  var remote = panel.querySelector('[data-port-name="' + parentPort + '"]');
  var metals = panel.querySelectorAll('[data-chassis]');
  if (!local || !remote || !metals.length) return;
  var grey = panel.getBoundingClientRect();
  var port = local.getBoundingClientRect();
  var far = remote.getBoundingClientRect();
  var chassisBottom = 0;
  for (var i = 0; i < metals.length; i++) chassisBottom = Math.max(chassisBottom, metals[i].getBoundingClientRect().bottom);
  var x = port.left - grey.left + port.width / 2;
  var y = port.top - grey.top + port.height / 2;
  var lane = Math.min(grey.height - 8, chassisBottom - grey.top + 8);
  var endX = far.left - grey.left + far.width / 2;
  var endY = far.top - grey.top + far.height / 2;
  var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 ' + grey.width + ' ' + grey.height);
  svg.setAttribute('style', 'position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none');
  var sleeve = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  var core = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  var d = 'M ' + Math.round(x) + ' ' + Math.round(y) + ' V ' + Math.round(lane) + ' H ' + Math.round(endX) + ' V ' + Math.round(endY);
  sleeve.setAttribute('d', d);
  sleeve.setAttribute('fill', 'none');
  sleeve.setAttribute('stroke', '#1e293b');
  sleeve.setAttribute('stroke-width', '7');
  core.setAttribute('d', d);
  core.setAttribute('fill', 'none');
  core.setAttribute('stroke', '#3b82f6');
  core.setAttribute('stroke-width', '3');
  svg.appendChild(sleeve);
  svg.appendChild(core);
  panel.appendChild(svg);
})();
</script>`;

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
      const html = `<!doctype html><html><head><meta charset="utf-8"><style>${SHOT_CSS}</style></head><body style="margin:0;background:#f8fafc">${container.innerHTML}${CABLE_SCRIPT}</body></html>`;
      fs.writeFileSync(path.join(dir, `${name}.html`), html);
      unmount();
    }
    expect(fs.existsSync(path.join(dir, 'no-parent.html'))).toBe(true);
  });
});

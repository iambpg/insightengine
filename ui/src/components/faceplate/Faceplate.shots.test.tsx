import React from 'react';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { FaceplateDevice, StackMember, StackMemberInfo } from '@/lib/types';
import { buildFaceplateFor } from '@/lib/mockData';
import StackBadge from '@/app/device-detail/components/StackBadge';
import Faceplate from './Faceplate';
import ParentPortPicture from './ParentPort';

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

function tiles(count: number, master: number): StackMemberInfo[] {
  return Array.from({ length: count }, (_, index) => {
    const number = index + 1;
    return {
      number,
      role: number === master ? 'active' : 'member',
      master: number === master,
      state: 'ready',
      health: 'healthy',
    };
  });
}

// Grey panel content is 1192px. The divider and the parent column take 193px, so the chassis fills the rest.
const PANEL_SPAN = 1200 - 8 - 1 - 16 - 176;

function frame(device: FaceplateDevice, parent: string | null, activeMember?: number, tileCount?: number) {
  const uplinkMember = device.form_factor === 'switch-stack' ? (activeMember || 1) : 1;
  return (
    <div style={{ width: 1200, background: '#f8fafc' }}>
      {tileCount ? (
        <div style={{ display: 'flex', alignItems: 'center', height: 72, padding: '0 12px', boxSizing: 'border-box' }}>
          <StackBadge members={tiles(tileCount, 1)} selected={activeMember || 1} />
        </div>
      ) : null}
      <div
      data-faceplate-panel=""
      data-uplink={parent ? `Te${uplinkMember}/1/1` : ''}
      data-parent-port={parent ? 'Te1/0/13' : ''}
      style={{ position: 'relative', display: 'flex', alignItems: 'stretch', width: 1200, height: 168, background: '#f8fafc', boxSizing: 'border-box', padding: 4, overflow: 'hidden' }}
    >
      <div style={{ width: PANEL_SPAN, minWidth: 0, display: 'flex', alignItems: 'flex-start' }}>
        <Faceplate device={device} activeMember={activeMember} spanWidth={PANEL_SPAN} caption={false} health={parent ? 'healthy' : 'unknown'} chassisLabel={device.form_factor === 'access-switch-48' ? 'C9300-48P' : 'C9300-24P'} />
      </div>
      <div style={{ width: 1, background: '#e2e8f0', margin: '0 8px' }} />
      <aside style={{ width: 176, display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '4px 8px' }}>
        <div style={{ font: '600 10px/1.2 ui-sans-serif, system-ui', letterSpacing: '0.08em', color: '#64748b', textTransform: 'uppercase' }}>Parent Device</div>
        {parent ? (
          <>
            <div style={{ marginTop: 6, font: '600 14px/1.2 ui-monospace, monospace', color: '#0f172a' }}>{parent}</div>
            <div style={{ marginTop: 8 }}>
              <ParentPortPicture name="Te1/0/13" up />
            </div>
          </>
        ) : (
          <div style={{ marginTop: 6, font: '500 14px/1.3 ui-sans-serif, system-ui', color: '#64748b' }}>No parent detected</div>
        )}
      </aside>
    </div>
    </div>
  );
}

const SHOT_CSS = `:root{--navy:#0b1220;--metal-1:#2a3140;--metal-2:#1b212d;--metal-3:#12161f;--metal-hi:#4a5468;--down:#d5deea;--font-mono:ui-monospace,monospace;--success:#17a672;--warning:#e8a317;--destructive:#d93a46;--cyan:#36cfff}
[data-tone="green"]{background-color:#22c55e;background-image:linear-gradient(180deg,rgba(255,255,255,.75) 0%,rgba(255,255,255,0) 32%),linear-gradient(180deg,#dcfce7 0%,#22c55e 48%,#15803d 100%)}
[data-tone="amber"]{background-color:#f59e0b;background-image:linear-gradient(180deg,rgba(255,255,255,.75) 0%,rgba(255,255,255,0) 32%),linear-gradient(180deg,#fef3c7 0%,#f59e0b 48%,#b45309 100%)}
[data-tone="red"]{background-color:#ef4444;background-image:linear-gradient(180deg,rgba(255,255,255,.75) 0%,rgba(255,255,255,0) 32%),linear-gradient(180deg,#fecaca 0%,#ef4444 48%,#991b1b 100%)}
[data-tone="grey"]{background-color:#94a3b8;background-image:linear-gradient(180deg,rgba(255,255,255,.75) 0%,rgba(255,255,255,0) 32%),linear-gradient(180deg,#f8fafc 0%,#94a3b8 48%,#64748b 100%)}
button{font-family:ui-sans-serif,system-ui,sans-serif}`;

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
  var endY = far.height <= 12 ? far.top - grey.top + 2 : far.bottom - grey.top - 4;
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

describe('stack faceplate', () => {
  it('draws the master chassis until another member number is selected', () => {
    const { container, rerender } = render(<Faceplate device={stack(2)} caption={false} />);
    expect(container.querySelectorAll('[data-chassis]')).toHaveLength(1);
    expect(container.querySelector('[aria-label="Stack member 1"]')).toBeTruthy();
    rerender(<Faceplate device={stack(2)} caption={false} activeMember={2} />);
    expect(container.querySelectorAll('[data-chassis]')).toHaveLength(1);
    expect(container.querySelector('[aria-label="Stack member 2"]')).toBeTruthy();
    expect(container.querySelector('[aria-label="Stack member 1"]')).toBeNull();
  });

  it('draws the chassis across the grey panel up to the parent divider', () => {
    const { container } = render(<Faceplate device={stack(2)} caption={false} spanWidth={PANEL_SPAN} />);
    const metal = container.querySelector('[data-chassis] rect');
    expect(metal).toBeTruthy();
    expect(Number(metal?.getAttribute('width'))).toBeGreaterThan(900);
    expect(container.querySelectorAll('[data-chassis]')).toHaveLength(1);
  });
});

describe('faceplate screenshots', () => {
  it('writes the panel frames when IE_FACEPLATE_SHOTS is set', () => {
    if (process.env.IE_FACEPLATE_SHOTS !== '1') return;
    const stack4 = stack(4);
    const member3 = {
      ...stack4,
      members: stack4.members?.map((member) => (member.number === 3 ? { ...member, health: 'fault' as const } : member)),
    };
    const cases: Array<[string, FaceplateDevice, string | null, number | undefined, number | undefined]> = [
      ['standalone', buildFaceplateFor('access-switch-24'), 'dist-sw-02', undefined, undefined],
      ['stack-2', stack(2), 'dist-sw-02', 1, 2],
      ['stack-2-member-02', stack(2), 'dist-sw-02', 2, 2],
      ['stack-4', member3, 'dist-sw-02', 3, 4],
      ['no-parent', buildFaceplateFor('access-switch-24'), null, undefined, undefined],
    ];
    const dir = process.env.IE_FACEPLATE_SHOT_DIR || path.join(os.tmpdir(), 'faceplate-shots');
    fs.mkdirSync(dir, { recursive: true });
    for (const [name, device, parent, activeMember, tileCount] of cases) {
      const { container, unmount } = render(frame(device, parent, activeMember, tileCount));
      const html = `<!doctype html><html><head><meta charset="utf-8"><style>${SHOT_CSS}</style></head><body style="margin:0;background:#f8fafc">${container.innerHTML}${CABLE_SCRIPT}</body></html>`;
      fs.writeFileSync(path.join(dir, `${name}.html`), html);
      unmount();
    }
    expect(fs.existsSync(path.join(dir, 'no-parent.html'))).toBe(true);
  });
});

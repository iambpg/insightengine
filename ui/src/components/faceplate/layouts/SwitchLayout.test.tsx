import React from 'react';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { PortInfo } from '@/lib/types';
import SwitchLayout, { cablePorts, faceNumber, silkLabel } from './SwitchLayout';

function port(name: string, type: PortInfo['type'] = 'RJ45'): PortInfo {
  return { id: name, name, type, speed: '1G', state: 'up', utilisation: 0, errors: 0 };
}

describe('faceplate numbers follow the interface', () => {
  it('reads the last number, so 1 is Gi0/1, Fa0/1 or Gi1/0/1', () => {
    expect(faceNumber('Gi0/1')).toBe(1);
    expect(faceNumber('FastEthernet0/1')).toBe(1);
    expect(faceNumber('GigabitEthernet1/0/1')).toBe(1);
    expect(faceNumber('GigabitEthernet1/0/24')).toBe(24);
    expect(faceNumber('Gi0/0')).toBe(0);
  });

  it('puts a port numbered 0 after the numbered access ports', () => {
    const ordered = cablePorts([
      port('GigabitEthernet0/0'),
      port('GigabitEthernet0/2'),
      port('TenGigabitEthernet1/1/1', 'SFP+'),
      port('GigabitEthernet0/1'),
    ]).map((item) => item.name);
    expect(ordered).toEqual(['GigabitEthernet0/1', 'GigabitEthernet0/2', 'GigabitEthernet0/0', 'TenGigabitEthernet1/1/1']);
  });

  it('groups 1/1/1 through 1/1/4 at the end and does not reuse access numbers', () => {
    const ordered = cablePorts([
      port('TenGigabitEthernet1/1/4', 'SFP+'),
      port('GigabitEthernet1/0/1'),
      port('TenGigabitEthernet1/1/1', 'SFP+'),
      port('GigabitEthernet1/0/2'),
      port('TenGigabitEthernet1/1/2', 'SFP+'),
      port('TenGigabitEthernet2/1/1', 'SFP+'),
      port('GigabitEthernet1/0/4'),
    ]).map((item) => item.name);
    expect(ordered).toEqual([
      'GigabitEthernet1/0/1',
      'GigabitEthernet1/0/2',
      'GigabitEthernet1/0/4',
      'TenGigabitEthernet1/1/1',
      'TenGigabitEthernet1/1/2',
      'TenGigabitEthernet1/1/4',
      'TenGigabitEthernet2/1/1',
    ]);
    expect(silkLabel('GigabitEthernet1/0/1')).toBe('1');
    expect(silkLabel('TenGigabitEthernet1/1/1')).toBe('1/1/1');
    expect(silkLabel('TenGigabitEthernet1/1/4')).toBe('1/1/4');
  });

  it('draws the interface number inside the port that the hover reads', () => {
    const { container } = render(
      <svg>
        <SwitchLayout
          uid="t"
          ports={[port('GigabitEthernet0/0'), port('GigabitEthernet0/1'), port('Fa0/2')]}
          selectedId={null}
          onHover={() => undefined}
          onSelect={() => undefined}
        />
      </svg>,
    );
    const one = container.querySelector('[data-port-name="GigabitEthernet0/1"]');
    const zero = container.querySelector('[data-port-name="GigabitEthernet0/0"]');
    expect(one?.textContent).toContain('1');
    expect(zero?.textContent).toContain('0');
    expect(one?.compareDocumentPosition(zero!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

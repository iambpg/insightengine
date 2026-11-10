import React from 'react';
import { readFileSync } from 'fs';
import path from 'path';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { FaceplateModel } from '../library/catalog';
import type { PortInfo } from '@/lib/types';
import FortiGateLayout from './FortiGateLayout';

function port(name: string, state: PortInfo['state'] = 'up'): PortInfo {
  return { id: name, name, type: 'RJ45', speed: '1 Gbps', state, utilisation: 0, errors: 0, description: name === 'wan1' ? 'bb1' : '' };
}

describe('FortiGate drawn faceplate', () => {
  it('draws switch ports in the 60F image order and does not use the picture', () => {
    const model = JSON.parse(readFileSync(path.resolve(__dirname, '../../../../public/faceplates/models/fortinet-fg-60f.json'), 'utf8')) as FaceplateModel;
    const { container } = render(
      <svg>
        <FortiGateLayout
          model={model}
          ports={[port('wan1'), port('wan2'), port('internal1', 'up'), port('dmz', 'not-connected')]}
          uid="fg"
          selectedId={null}
          onHover={vi.fn()}
          onSelect={vi.fn()}
        />
      </svg>,
    );
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByRole('button', { name: /wan1, bb1, Up/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /wan2, Up/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /internal1, Up/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /dmz, Not connected/ })).toBeInTheDocument();
    const labels = [...container.querySelectorAll('text')].map((node) => node.textContent);
    const wan1 = labels.indexOf('wan1');
    const internal1 = labels.indexOf('internal1');
    const dmz = labels.indexOf('dmz');
    expect(wan1).toBeGreaterThanOrEqual(0);
    expect(wan1).toBeLessThan(internal1);
    expect(internal1).toBeLessThan(dmz);
  });
});

import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { FaceplateDevice, PortInfo } from '@/lib/types';
import type { FaceplateModel } from './library/catalog';
import RealisticFaceplate from './RealisticFaceplate';
import Faceplate from './Faceplate';

function port(name: string, id = name): PortInfo {
  return {
    id,
    name,
    type: 'RJ45',
    speed: '1 Gbps',
    state: 'up',
    utilisation: 12,
    errors: 0,
  };
}

function model(source: FaceplateModel['source'], raster: boolean, portName: string): FaceplateModel {
  return {
    slug: `sample-${source}`,
    model: `Sample ${source}`,
    partNumber: 'X',
    manufacturer: 'Cisco',
    vendor: 'cisco',
    source,
    front: raster ? '/faceplates/library/cisco/sample.front.png' : '/faceplates/visio/cisco/sample.front.svg',
    rear: '',
    width: 1000,
    height: 200,
    raster,
    ports: [{ name: portName, x: 0.2, y: 0.3, w: 0.05, h: 0.2 }],
  };
}

function device(name: string): FaceplateDevice {
  return {
    form_factor: 'access-switch-24',
    role: 'Access switch',
    ports: [port(name)],
  };
}

describe('realistic faceplates', () => {
  it.each([
    ['photo', true],
    ['visio', false],
    ['vendor', true],
    ['drawn', false],
  ] as const)('clicking a %s port calls the same select handler and the picture does not', async (source, raster) => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <RealisticFaceplate
        device={device('Gi1/0/1')}
        model={model(source, raster, 'GigabitEthernet1/0/1')}
        onHover={() => undefined}
        onSelect={onSelect}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Zoom' })).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
    const face = screen.getByTestId('realistic-faceplate');
    expect(face).toHaveAttribute('data-faceplate-source', source);
    expect(face).toHaveAttribute('viewBox', '0 0 1000 200');
    expect(face).toHaveStyle({ position: 'absolute', left: '0px', top: '0px', width: '1000px', height: '200px' });
    const picture = screen.getByTestId('faceplate-image');
    expect(picture).toHaveAttribute('width', '1000');
    expect(picture).toHaveAttribute('height', '200');
    expect(picture).toHaveStyle({ objectFit: 'fill', width: '1000px', height: '200px', pointerEvents: 'none' });
    const stage = screen.getByTestId('faceplate-stage');
    expect(stage).toHaveStyle({ padding: '0px', width: '1000px', height: '200px' });
    await user.click(face);
    expect(onSelect).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: /Gi1\/0\/1, Up/ }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0][0].name).toBe('Gi1/0/1');
    const hotspot = screen.getByTestId('port-hotspot-GigabitEthernet1/0/1');
    const rect = hotspot.querySelector('rect');
    expect(rect).toHaveAttribute('x', '200');
    expect(rect).toHaveAttribute('y', '60');
    expect(Number(rect?.getAttribute('width'))).toBeGreaterThan(0);
    expect(Number(rect?.getAttribute('height'))).toBeGreaterThan(0);
  });

  it('puts a stack member port on the same faceplate opening', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <RealisticFaceplate
        device={device('Gi2/0/1')}
        model={model('visio', false, 'GigabitEthernet1/0/1')}
        onHover={() => undefined}
        onSelect={onSelect}
      />,
    );
    await user.click(screen.getByRole('button', { name: /Gi2\/0\/1, Up/ }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    const hotspot = screen.getByTestId('port-hotspot-GigabitEthernet1/0/1');
    expect(hotspot.querySelector('rect')).toHaveAttribute('x', '200');
    expect(hotspot.querySelector('rect')).toHaveAttribute('y', '60');
  });

  it('places a non-Cisco port on the first 9200L opening', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <RealisticFaceplate
        device={device('port1')}
        model={model('visio', false, 'GigabitEthernet1/0/1')}
        onHover={() => undefined}
        onSelect={onSelect}
      />,
    );
    await user.click(screen.getByRole('button', { name: /port1, Up/ }));
    expect(onSelect.mock.calls[0][0].name).toBe('port1');
    expect(screen.getByTestId('port-hotspot-GigabitEthernet1/0/1').querySelector('rect')).toHaveAttribute('x', '200');
  });

  it('opens the drawn faceplate port through the same handler', async () => {
    const onSelectPort = vi.fn();
    const user = userEvent.setup();
    render(
      <Faceplate
        device={device('Gi1/0/1')}
        onSelectPort={onSelectPort}
      />,
    );
    const portButton = await screen.findByRole('button', { name: /Gi1\/0\/1, Up/ });
    await user.click(portButton);
    expect(onSelectPort).toHaveBeenCalledTimes(1);
    expect(onSelectPort.mock.calls[0][0].id).toBe('Gi1/0/1');
  });
});

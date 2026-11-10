import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import Faceplate from './Faceplate';
import { CHASSIS_WIDTH, FACEPLATE_HEIGHT, lockedChassis } from './size';

vi.mock('./library/catalog', () => ({
  useFaceplateModel: () => ({
    slug: 'cisco-cw9164',
    model: 'CW9164',
    partNumber: 'CW9164',
    manufacturer: 'Cisco',
    vendor: 'cisco',
    source: 'visio',
    front: '/faceplates/visio/cisco/ap.front.svg',
    rear: '',
    width: 400,
    height: 200,
    raster: false,
    ports: [{ name: 'eth0', x: 0.2, y: 0.3, w: 0.08, h: 0.2 }],
  }),
}));

describe('access point faceplate', () => {
  it('keeps the access point drawing when a catalog picture exists', () => {
    render(
      <Faceplate
        device={{
          form_factor: 'ceiling-ap',
          role: 'Access point',
          hostname: 'wc18-ms-ap07',
          apState: 'up',
          ports: [{ id: 'eth0', name: 'GigabitEthernet0', type: 'RJ45', speed: '1 Gbps', state: 'up', utilisation: 0, errors: 0 }],
          radios: [],
        }}
      />,
    );
    expect(screen.getByText('TOP VIEW')).toBeInTheDocument();
    expect(screen.getByText('SIDE VIEW')).toBeInTheDocument();
    expect(screen.queryByTestId('faceplate-image')).toBeNull();
    const frame = lockedChassis();
    const svg = document.querySelector('svg');
    expect(svg).toHaveAttribute('viewBox', `0 0 ${frame.vbW} ${frame.vbH}`);
    expect(svg).toHaveStyle({ width: '100%', aspectRatio: `${CHASSIS_WIDTH} / ${FACEPLATE_HEIGHT}` });
  });
});

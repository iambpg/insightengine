import React, { useRef } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { PortInfo } from '@/lib/types';
import { UplinkCable } from './DeviceDetailView';
import { cableFlow, portIsUplink, rectsOverlap } from './uplinkCable';

function port(over: Partial<PortInfo> = {}): PortInfo {
  return { id: 'uplink', name: 'TenGigabitEthernet1/1/1', type: 'SFP+', speed: '10 Gbps', state: 'up', utilisation: 0, errors: 0, ...over };
}

function rect(left: number, top: number, width: number, height: number): DOMRect {
  return { left, top, right: left + width, bottom: top + height, width, height, x: left, y: top, toJSON() { return {}; } } as DOMRect;
}

function Host({ flow, place }: { flow: ReturnType<typeof cableFlow>; place: 'visible' | 'scrolled' }) {
  const localRef = useRef<HTMLDivElement>(null);
  const greyRef = useRef<HTMLDivElement>(null);
  const remoteRef = useRef<HTMLDivElement>(null);
  return (
    <div
      ref={(node) => {
        if (!node) return;
        const grey = node.querySelector('[data-grey]') as HTMLDivElement;
        const local = node.querySelector('[data-local]') as HTMLDivElement;
        const remote = node.querySelector('[data-remote]') as HTMLDivElement;
        const jack = node.querySelector('[data-port-name="Te1/1/1"]') as HTMLDivElement;
        const far = node.querySelector('[data-port-name="Te1/0/13"]') as HTMLDivElement;
        grey.getBoundingClientRect = () => rect(0, 0, 800, 168);
        local.getBoundingClientRect = () => rect(0, 0, 600, 168);
        remote.getBoundingClientRect = () => rect(620, 20, 160, 120);
        jack.getBoundingClientRect = () => (place === 'visible' ? rect(520, 80, 12, 8) : rect(-40, 80, 12, 8));
        far.getBoundingClientRect = () => rect(680, 90, 16, 10);
        localRef.current = local;
        greyRef.current = grey;
        remoteRef.current = remote;
      }}
    >
      <div data-grey="">
        <div data-local="">
          <div data-chassis="" />
          <div data-port-name="Te1/1/1" />
        </div>
        <div data-remote="">
          <div data-port-name="Te1/0/13" />
        </div>
      </div>
      <CableMount localRef={localRef} greyRef={greyRef} remoteRef={remoteRef} flow={flow} />
    </div>
  );
}

function CableMount({
  localRef,
  greyRef,
  remoteRef,
  flow,
}: {
  localRef: React.RefObject<HTMLDivElement | null>;
  greyRef: React.RefObject<HTMLDivElement | null>;
  remoteRef: React.RefObject<HTMLDivElement | null>;
  flow: ReturnType<typeof cableFlow>;
}) {
  const remote = remoteRef.current;
  if (!remote) return null;
  return <UplinkCable localRef={localRef} greyRef={greyRef} remote={remote} localPortName="Te1/1/1" remotePortName="Te1/0/13" flow={flow} />;
}

describe('uplink cable', () => {
  it('matches the clicked faceplate port to the parent uplink name', () => {
    expect(portIsUplink(port(), 'Te1/1/1')).toBe(true);
    expect(portIsUplink(port({ names: ['Te1/1/1'] }), 'Te1/1/1')).toBe(true);
    expect(portIsUplink(port({ name: 'GigabitEthernet1/0/4' }), 'Te1/1/1')).toBe(false);
    expect(portIsUplink(null, 'Te1/1/1')).toBe(false);
  });

  it('treats a jack scrolled off the faceplate as out of view', () => {
    expect(rectsOverlap(rect(520, 80, 12, 8), rect(0, 0, 600, 168))).toBe(true);
    expect(rectsOverlap(rect(-40, 80, 12, 8), rect(0, 0, 600, 168))).toBe(false);
  });

  it('moves inside the cable only while the port is passing traffic', () => {
    expect(cableFlow(port())).toBeNull();
    expect(cableFlow(port({ state: 'down', utilisation: 90, inBps: 1_000_000 }))).toBeNull();
    const quiet = cableFlow(port({ utilisation: 4 }));
    const busy = cableFlow(port({ utilisation: 90, inBps: 8_000_000, outBps: 1_000_000 }));
    expect(quiet).toMatchObject({ outbound: true, inbound: false });
    expect(busy).toMatchObject({ outbound: true, inbound: true });
    expect(busy!.seconds).toBeLessThan(quiet!.seconds);
  });

  it('draws the cable when the uplink is clicked and on screen, and animates only with traffic', () => {
    const live = cableFlow(port({ utilisation: 40, outBps: 2_000_000 }));
    const shown = render(<Host flow={live} place="visible" />);
    shown.rerender(<Host flow={live} place="visible" />);
    expect(screen.getByTestId('uplink-cable')).toHaveAttribute('data-cable-flow', 'live');
    expect(screen.getByTestId('cable-flow-out').getAttribute('style')).toContain('ie-cable-flow');
    expect(screen.queryByTestId('cable-flow-in')).toBeNull();
    shown.unmount();

    const idle = render(<Host flow={null} place="visible" />);
    idle.rerender(<Host flow={null} place="visible" />);
    expect(screen.getByTestId('uplink-cable')).toHaveAttribute('data-cable-flow', 'idle');
    expect(screen.queryByTestId('cable-flow-out')).toBeNull();
    idle.unmount();

    const hidden = render(<Host flow={live} place="scrolled" />);
    hidden.rerender(<Host flow={live} place="scrolled" />);
    expect(screen.queryByTestId('uplink-cable')).toBeNull();
  });
});

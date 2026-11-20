import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ZoomableChart from '@/components/charts/ZoomableChart';

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;

describe('ZoomableChart', () => {
  it('names the window, the series, and the latest reading', () => {
    const end = Date.now();
    render(
      <ZoomableChart
        data={[
          { t: end - 60_000, label: 'old', inBps: 10, outBps: 4 },
          { t: end, label: 'now', inBps: 12.5, outBps: 6 },
        ]}
        series={[
          { key: 'inBps', label: 'Inbound', color: '#0f766e' },
          { key: 'outBps', label: 'Outbound', color: '#0369a1' },
        ]}
        kind="line"
        unit="Mbps"
        gradientId="throughput"
        subject="Traffic in and out of the uplinks, in megabits per second."
        windowLabel="Last 5 minutes"
      />,
    );
    expect(screen.getByTestId('chart-window')).toHaveTextContent('Last 5 minutes');
    expect(screen.getByText('Traffic in and out of the uplinks, in megabits per second.')).toBeInTheDocument();
    expect(screen.getByText('Inbound')).toBeInTheDocument();
    expect(screen.getByText('12.5 Mbps')).toBeInTheDocument();
    expect(screen.getByText('6 Mbps')).toBeInTheDocument();
  });
});

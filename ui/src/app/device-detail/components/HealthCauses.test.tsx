import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { HealthCause } from '@/lib/types';
import HealthCauses from './HealthCauses';

const items: HealthCause[] = [
  { id: '1', severity: 'critical', title: 'Probe failed', detail: 'ICMP is down', value: '0', threshold: '1', source: 'prometheus', since: '6m ago', target: 'probe' },
  { id: '2', severity: 'warning', title: 'CPU high', detail: 'Above 80%', value: '83%', threshold: '80%', source: 'prometheus', since: '15m ago', target: 'cpu' },
  { id: '3', severity: 'info', title: 'Firmware notice', detail: 'A newer release exists', value: 'notice', threshold: '—', source: 'alertmanager', since: '14d ago', target: 'system' },
];

describe('HealthCauses', () => {
  it('lists every cause and filters by the severity chip', async () => {
    const user = userEvent.setup();
    const onFilter = vi.fn();
    const { rerender } = render(<HealthCauses items={items} health="critical" filter="critical" onFilter={onFilter} />);
    expect(screen.getByRole('heading', { name: 'Health' })).toBeInTheDocument();
    expect(screen.getByText('Probe failed')).toBeInTheDocument();
    expect(screen.queryByText('CPU high')).toBeNull();
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.getByText('prometheus')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Warning/ }));
    expect(onFilter).toHaveBeenCalledWith('warning');
    rerender(<HealthCauses items={items} health="critical" filter="warning" onFilter={onFilter} />);
    expect(screen.getByText('CPU high')).toBeInTheDocument();
    expect(screen.getByText('83%')).toBeInTheDocument();
    expect(screen.queryByText('Probe failed')).toBeNull();
  });

  it('says the device is healthy when nothing is wrong', () => {
    render(<HealthCauses items={[]} health="healthy" filter="all" onFilter={() => undefined} />);
    expect(screen.getByText('No issues — healthy')).toBeInTheDocument();
  });
});

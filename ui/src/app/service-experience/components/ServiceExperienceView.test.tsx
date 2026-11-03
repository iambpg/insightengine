import React from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/apiClient';
import ServiceExperienceView from './ServiceExperienceView';

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

vi.mock('@/lib/apiClient', () => ({
  api: { getExperience: vi.fn() },
}));

const empty = {
  isExampleData: false,
  degraded: [],
  wlc: { configured: false, reason: 'not configured. No wireless controller is in NetBox.' },
  sdwan: { configured: false, reason: 'not configured. No Cisco SD-WAN cEdge is in NetBox.' },
  vbs: { configured: false, reason: 'not configured. No site has vbs_server_ip.' },
  thirdParties: { configured: false, reason: 'not configured. No NetBox service is tagged third-party or bank.' },
};

describe('Service Experience', () => {
  beforeEach(() => {
    vi.mocked(api.getExperience).mockReset();
  });

  it('shows not configured when NetBox has none of the sources', async () => {
    vi.mocked(api.getExperience).mockResolvedValue(empty);
    render(<ServiceExperienceView />);
    expect(await screen.findByText(/No wireless controller is in NetBox/)).toBeInTheDocument();
    expect(screen.getByText(/No Cisco SD-WAN cEdge/)).toBeInTheDocument();
    expect(screen.getByText(/No site has vbs_server_ip/)).toBeInTheDocument();
    expect(screen.getByText(/No NetBox service is tagged/)).toBeInTheDocument();
  });

  it('lists a controller when wireless is configured and has no samples yet', async () => {
    vi.mocked(api.getExperience).mockResolvedValue({
      ...empty,
      wlc: {
        configured: true,
        reason: '',
        note: 'Catalyst 9800 uses MDT.',
        controllers: [{ name: 'wlc-9800', transport: 'mdt' }],
        radios: [],
      },
    });
    render(<ServiceExperienceView />);
    expect(await screen.findByText('wlc-9800')).toBeInTheDocument();
    expect(screen.getByText('Catalyst 9800 uses MDT.')).toBeInTheDocument();
  });
});

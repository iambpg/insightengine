import type { RoleName } from '@/lib/types';

export interface DemoAccount {
  role: RoleName;
  email: string;
  password: string;
}

/** Demo passwords exist only for NEXT_PUBLIC_IE_API_MODE=mock. Production builds alias this file away. */
export const DEMO_ACCOUNTS: DemoAccount[] = [
  { role: 'Administrator', email: 'm.vanderberg@noc.example', password: 'Midnight#Admin26' },
  { role: 'Engineer', email: 's.kuipers@noc.example', password: 'Faceplate#Eng26' },
  { role: 'Operator', email: 'd.pranata@noc.example', password: 'Telemetry#Ops26' },
  { role: 'Read-only', email: 'f.smit@customer.example', password: 'ReadOnly#View26' },
];

export function mockLogin(
  email: string,
  password: string
): {
  ok: boolean;
  role?: RoleName;
  email?: string;
  csrfToken?: string;
  error?: string;
} {
  const account = DEMO_ACCOUNTS.find((item) => item.email === email.trim().toLowerCase());
  if (!account || account.password !== password) {
    return {
      ok: false,
      error: 'Invalid credentials. Use a demo account below, or check the password.',
    };
  }
  return {
    ok: true,
    role: account.role,
    email: account.email,
    csrfToken: `mock-csrf-${account.role}`,
  };
}

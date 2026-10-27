import type { RoleName } from '@/lib/types';

export interface DemoAccount {
  role: RoleName;
  email: string;
  password: string;
}

export const DEMO_ACCOUNTS: DemoAccount[] = [];

export function mockLogin(): {
  ok: boolean;
  role?: RoleName;
  email?: string;
  csrfToken?: string;
  error?: string;
} {
  return { ok: false, error: 'Demo accounts are not included in this build.' };
}

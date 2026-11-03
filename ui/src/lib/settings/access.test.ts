import { describe, expect, it } from 'vitest';
import { allowOperate, allowSettings, canManageUsers, canOperate, canSeeVault, isViewerRole } from './access';

describe('role access', () => {
  it('treats Administrator as Admin and Read-only as Viewer', () => {
    expect(canManageUsers('Administrator')).toBe(true);
    expect(canManageUsers('Admin')).toBe(true);
    expect(canSeeVault('Administrator')).toBe(true);
    expect(canManageUsers('Engineer')).toBe(false);
    expect(canManageUsers('Operator')).toBe(false);
    expect(isViewerRole('Read-only')).toBe(true);
    expect(isViewerRole('Viewer')).toBe(true);
    expect(canOperate('Operator')).toBe(true);
    expect(canOperate('Read-only')).toBe(false);
    expect(allowOperate(null)).toBe(true);
    expect(allowOperate('Viewer')).toBe(false);
    expect(allowSettings('Engineer')).toBe(true);
    expect(allowSettings('Operator')).toBe(false);
  });
});

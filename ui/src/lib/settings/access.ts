import type { RoleName } from '@/lib/types';
import type { SettingsAction, SettingsFileMeta } from '@/lib/contract';

/** Administrator is the stored Admin role. Read-only is the stored Viewer role. */
export function isAdminRole(role: string | null | undefined): boolean {
  return role === 'Administrator' || role === 'Admin';
}

export function isViewerRole(role: string | null | undefined): boolean {
  return role === 'Read-only' || role === 'Viewer';
}

export function canOperate(role: string | null | undefined): boolean {
  return isAdminRole(role) || role === 'Engineer' || role === 'Operator';
}

/** Unsigned screens keep their controls; the API still enforces the role. */
export function allowOperate(role: string | null | undefined): boolean {
  if (!role) return true;
  return canOperate(role);
}

export function allowSettings(role: string | null | undefined): boolean {
  if (!role) return true;
  return isAdminRole(role) || role === 'Engineer';
}

export function canSeeApplications(role: RoleName | null | undefined): boolean {
  return role === 'Administrator' || role === 'Admin' || role === 'Engineer';
}

export function canSeeVault(role: RoleName | null | undefined): boolean {
  return isAdminRole(role);
}

export function canManageUsers(role: string | null | undefined): boolean {
  return isAdminRole(role);
}

export function canRunAction(role: RoleName | null | undefined, action: SettingsAction): boolean {
  if (!role) return false;
  if (action.dangerous && !isAdminRole(role)) return false;
  return action.roles.includes(role) || (isAdminRole(role) && action.roles.includes('Administrator'));
}

export function canEditFile(
  role: RoleName | null | undefined,
  file: SettingsFileMeta | undefined
): boolean {
  if (!file || !file.editable) return false;
  return isAdminRole(role) || role === 'Engineer';
}

import type { RoleName } from '@/lib/types';
import type { SettingsAction, SettingsFileMeta } from '@/lib/contract';

export function canSeeApplications(
  role: RoleName | null | undefined
): role is 'Administrator' | 'Engineer' {
  return role === 'Administrator' || role === 'Engineer';
}

export function canSeeVault(role: RoleName | null | undefined): role is 'Administrator' {
  return role === 'Administrator';
}

export function canRunAction(role: RoleName | null | undefined, action: SettingsAction): boolean {
  if (!role) return false;
  if (action.dangerous && role !== 'Administrator') return false;
  return action.roles.includes(role);
}

export function canEditFile(
  role: RoleName | null | undefined,
  file: SettingsFileMeta | undefined
): boolean {
  if (!file || !file.editable) return false;
  return role === 'Administrator' || role === 'Engineer';
}

import type { ProjectMembership } from './api'

export type ProjectAccess = {
  canWrite: boolean
  canManageMembers: boolean
  role: string
}

export function resolveProjectAccess(membership?: ProjectMembership): ProjectAccess {
  if (!membership) {
    return { canWrite: false, canManageMembers: false, role: 'unknown' }
  }
  return {
    canWrite: membership.can_write,
    canManageMembers: membership.can_manage_members,
    role: membership.project_role || membership.organization_role || 'member',
  }
}

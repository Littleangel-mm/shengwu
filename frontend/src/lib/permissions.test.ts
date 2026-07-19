import { describe, expect, it } from 'vitest'
import { resolveProjectAccess } from './permissions'

describe('resolveProjectAccess', () => {
  it('keeps a viewer read-only', () => {
    expect(
      resolveProjectAccess({
        project_id: 'project',
        project_role: 'viewer',
        can_write: false,
        can_manage_members: false,
      }),
    ).toEqual({ canWrite: false, canManageMembers: false, role: 'viewer' })
  })

  it('allows an organization administrator to manage members', () => {
    expect(
      resolveProjectAccess({
        project_id: 'project',
        organization_role: 'admin',
        can_write: true,
        can_manage_members: true,
      }),
    ).toEqual({ canWrite: true, canManageMembers: true, role: 'admin' })
  })

  it('fails closed before membership is loaded', () => {
    expect(resolveProjectAccess()).toEqual({
      canWrite: false,
      canManageMembers: false,
      role: 'unknown',
    })
  })
})

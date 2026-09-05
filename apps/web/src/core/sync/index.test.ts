import { describe, expect, it } from 'vitest'

import { mapOutboxToOp, normalizeRow, reduceSyncState, type SyncState } from './index'

describe('normalizeRow 服务端行 → IndexedDB 行', () => {
  it('把 rev/updated_at/deleted_at 转成 _rev/_updated_at/_deleted_at', () => {
    const out = normalizeRow({ id: 't1', rev: 3, updated_at: 'x', deleted_at: null, title: '作业' })
    expect(out.id).toBe('t1')
    expect(out._rev).toBe(3)
    expect(out._updated_at).toBe('x')
    expect(out._deleted_at).toBeNull()
    expect(out.title).toBe('作业')
  })

  it('保留业务字段，去掉服务端只读通用列', () => {
    const out = normalizeRow({ id: 'c1', rev: 1, updated_at: 'u', deleted_at: 'd', name: '模电', color: 2 })
    expect(out.name).toBe('模电')
    expect(out.color).toBe(2)
    expect(out).not.toHaveProperty('rev')
    expect(out).not.toHaveProperty('updated_at')
    expect(out).not.toHaveProperty('deleted_at')
  })

  it('null 缺失值转 null', () => {
    const out = normalizeRow({ id: 'x', rev: 0, updated_at: undefined, deleted_at: undefined })
    expect(out._updated_at).toBeNull()
    expect(out._deleted_at).toBeNull()
  })
})

describe('mapOutboxToOp', () => {
  it('把 outbox 行映射成推送 op', () => {
    const op = mapOutboxToOp({
      op_id: 'op-1',
      entity: 'todo',
      id: 't1',
      set: { title: '写作业' },
      base_rev: 2,
    })
    expect(op).toEqual({ op_id: 'op-1', entity: 'todo', id: 't1', set: { title: '写作业' }, base_rev: 2 })
  })

  it('把软删除标记映射成同步 op', () => {
    const op = mapOutboxToOp({
      op_id: 'op-delete',
      entity: 'course_slot',
      id: 's1',
      set: {},
      base_rev: 3,
      deleted: true,
    })
    expect(op.deleted).toBe(true)
  })
})

describe('reduceSyncState 同步状态机', () => {
  const base: SyncState = { online: true, pending: 0, lastSyncAt: null, latestRev: 0, authInvalid: false }

  it('online 事件切换在线状态', () => {
    expect(reduceSyncState({ ...base, online: true }, { type: 'online', online: false }).online).toBe(false)
    expect(reduceSyncState({ ...base, online: false }, { type: 'online', online: true }).online).toBe(true)
  })

  it('pending 事件更新待传条数', () => {
    const s = reduceSyncState(base, { type: 'pending', pending: 5 })
    expect(s.pending).toBe(5)
  })

  it('synced 事件推进 latestRev 并打点、置为在线', () => {
    const s = reduceSyncState(base, { type: 'synced', latestRev: 42 })
    expect(s.latestRev).toBe(42)
    expect(s.online).toBe(true)
    expect(s.lastSyncAt).not.toBeNull()
    expect(s.authInvalid).toBe(false)
  })

  it('HTTP 同步成功会恢复 SSE 短暂断线造成的离线状态', () => {
    const offline = reduceSyncState(base, { type: 'online', online: false })
    const synced = reduceSyncState(offline, { type: 'synced', latestRev: 43 })
    expect(synced.online).toBe(true)
    expect(synced.authInvalid).toBe(false)
  })

  it('authInvalid 事件置为离线 + authInvalid=true', () => {
    const s = reduceSyncState(base, { type: 'authInvalid', invalid: true })
    expect(s.authInvalid).toBe(true)
    expect(s.online).toBe(false)
  })

  it('online=true 会清除 authInvalid', () => {
    const s = reduceSyncState({ ...base, authInvalid: true, online: false }, { type: 'online', online: true })
    expect(s.authInvalid).toBe(false)
    expect(s.online).toBe(true)
  })

  it('不改变 state 的其它字段', () => {
    const s = reduceSyncState({ ...base, pending: 3, latestRev: 7, online: false }, { type: 'online', online: true })
    expect(s.pending).toBe(3)
    expect(s.latestRev).toBe(7)
    expect(s.online).toBe(true)
  })
})

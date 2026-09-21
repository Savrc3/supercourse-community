/** 同步客户端：本地优先 + 串行后台同步 + 增量拉取 + SSE 订阅。 */

import type { Table } from 'dexie'

import { db, type SyncShadowRow } from '../../db/db'
import { getApiBase } from '../http'
import { isLocalMode } from '../connection'

const TOKEN_KEY = 'sc_token'
const CURSOR_KEY = 'sc_cursor'
export const SYNC_POLL_INTERVAL_MS = 5 * 60 * 1000
const SSE_SYNC_DELAY_MS = 800
const LOCAL_WRITE_SYNC_DELAY_MS = 300
const SYNC_RETRY_BASE_MS = 5 * 1000
const SYNC_RETRY_MAX_MS = 5 * 60 * 1000

export class AuthInvalidError extends Error {}

export interface SyncState {
  online: boolean
  pending: number
  lastSyncAt: number | null
  latestRev: number
  syncing: boolean
  lastError: string | null
  /** token 无效/未配对：应提示重新绑定而不是"离线"。 */
  authInvalid: boolean
}

export interface SyncChange {
  entity: string
  id: string
  rev: number
  deleted: boolean
}

/** 同步状态机的纯归约：对 state 做一次事件迁移。可单测。 */
export function reduceSyncState(
  state: SyncState,
  action:
    | { type: 'online'; online: boolean }
    | { type: 'pending'; pending: number }
    | { type: 'syncing'; syncing: boolean }
    | { type: 'synced'; latestRev: number }
    | { type: 'error'; message: string | null }
    | { type: 'authInvalid'; invalid: boolean },
): SyncState {
  switch (action.type) {
    case 'online':
      return { ...state, online: action.online, authInvalid: action.online ? false : state.authInvalid }
    case 'pending':
      return { ...state, pending: action.pending }
    case 'syncing':
      return { ...state, syncing: action.syncing }
    case 'synced':
      return {
        ...state,
        latestRev: action.latestRev,
        lastSyncAt: Date.now(),
        online: true,
        syncing: false,
        authInvalid: false,
      }
    case 'error':
      return { ...state, lastError: action.message, syncing: false }
    case 'authInvalid':
      return { ...state, authInvalid: action.invalid, online: false }
    default:
      return state
  }
}

export class SyncClient {
  private baseUrl: string
  private cursor: number = 0
  private eventSource: EventSource | null = null
  private pollTimer: number | null = null
  private syncTimer: number | null = null
  private syncingTimer: number | null = null
  private syncPromise: Promise<void> | null = null
  private syncQueued = false
  /** 已由本设备提交、等待增量游标回显的版本；这些回显不应再次让当前页面重载。 */
  private selfAckRevs = new Map<string, Set<number>>()
  /** 页面不重载时仍保留服务端确认的最新 rev，供下一次本地编辑使用。 */
  private knownRevs = new Map<string, number>()
  private retryAttempt = 0
  /** 服务端时间 - 本地时间（毫秒）：给 op 打与服务器可比的 updated_at。 */
  private clockOffsetMs = 0
  private readonly windowHandlers = new Map<string, () => void>()
  state: SyncState = {
    online: navigator.onLine,
    pending: 0,
    lastSyncAt: null,
    latestRev: 0,
    syncing: false,
    lastError: null,
    authInvalid: false,
  }
  private listeners = new Set<(s: SyncState) => void>()
  private changeListeners = new Set<(changes: SyncChange[]) => void>()

  constructor(baseUrl = getApiBase()) {
    this.baseUrl = baseUrl
    this.cursor = this.readCursor()
  }

  get token(): string | null {
    return localStorage.getItem(TOKEN_KEY)
  }

  setToken(token: string) {
    localStorage.setItem(TOKEN_KEY, token)
  }

  clearToken() {
    localStorage.removeItem(TOKEN_KEY)
    this.selfAckRevs.clear()
    this.knownRevs.clear()
  }

  setBaseUrl(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/+$/, '')
  }

  resetCursor() {
    this.cursor = 0
    localStorage.removeItem(CURSOR_KEY)
    this.selfAckRevs.clear()
    this.knownRevs.clear()
  }

  subscribe(fn: (s: SyncState) => void): () => void {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  subscribeChanges(fn: (changes: SyncChange[]) => void): () => void {
    this.changeListeners.add(fn)
    return () => this.changeListeners.delete(fn)
  }

  private emit() {
    this.listeners.forEach((fn) => fn({ ...this.state }))
  }

  private emitChanges(changes: SyncChange[]) {
    if (changes.length === 0) return
    this.changeListeners.forEach((fn) => fn(changes))
  }

  private readCursor(): number {
    return Number(localStorage.getItem(CURSOR_KEY) ?? 0)
  }

  private persistCursor(v: number) {
    this.cursor = v
    localStorage.setItem(CURSOR_KEY, String(v))
  }

  /** 记录服务端时间与本地时钟的差值：LWW 用客户端时间戳比较，必须同源。 */
  private noteServerTime(value: unknown) {
    if (typeof value !== 'string') return
    const server = Date.parse(value)
    if (Number.isNaN(server)) return
    this.clockOffsetMs = server - Date.now()
  }

  /** 按服务端时间轴给本地写入打戳（服务端仍会钳制未来超过 60 秒的戳）。 */
  private clientStamp(): string {
    return new Date(Date.now() + this.clockOffsetMs).toISOString()
  }

  private async request(path: string, init?: RequestInit): Promise<Response> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
        ...(init?.headers ?? {}),
      },
    })
    if (resp.status === 401) {
      throw new AuthInvalidError(`token invalid: ${path}`)
    }
    return resp
  }

  /** 首次全量。 */
  async bootstrap(): Promise<void> {
    if (isLocalMode()) return
    const resp = await this.request('/bootstrap')
    if (!resp.ok) throw new Error(`bootstrap failed ${resp.status}`)
    const data = await resp.json()
    await this.applySnapshot(data.snapshot ?? {})
    this.noteServerTime(data.server_time)
    this.persistCursor(data.latest_rev ?? 0)
    this.state.latestRev = data.latest_rev ?? 0
    this.state.lastSyncAt = Date.now()
    this.state.lastError = null
    this.emit()
  }

  /** 请求一次串行同步；连续触发会合并，不会并发访问服务器。 */
  async pull(): Promise<void> {
    this.scheduleSync(0)
    if (this.syncPromise) await this.syncPromise
  }

  /** 增量拉取，落库并推进游标。 */
  private async pullImpl(): Promise<void> {
    if (isLocalMode()) return
    try {
      const resp = await this.request(`/sync/changes?since=${this.cursor}&limit=500`)
      if (!resp.ok) throw new Error(`changes failed ${resp.status}`)
      const data = await resp.json()
      this.noteServerTime(data.server_time)
      let result: { changes: SyncChange[]; deferred: boolean }
      if (data.full && data.snapshot) {
        await this.applySnapshot(data.snapshot)
        result = { changes: [], deferred: false }
      } else {
        result = await this.applyChanges(data.changes ?? [])
      }
      this.persistCursor(data.next_cursor ?? data.latest_rev ?? 0)
      this.state = reduceSyncState(this.state, {
        type: 'synced',
        latestRev: data.latest_rev ?? 0,
      })
      this.emit()
      this.emitChanges(result.changes)
    } catch (e) {
      if (e instanceof AuthInvalidError) {
        this.state = reduceSyncState(this.state, { type: 'authInvalid', invalid: true })
        this.emit()
      } else {
        this.setOnline(false)
      }
      throw e
    }
  }

  /** 把 outbox 里的 op 推给服务端并落库结果。 */
  async flush(): Promise<void> {
    if (isLocalMode()) return
    const queue = (await db.outbox.orderBy('created_at').toArray()).filter((item) => !item.blocked)
    if (queue.length === 0) {
      await this.reconcileShadows()
      return
    }
    const batch = queue.slice(0, 100)
    const resp = await this.request('/sync/push', {
      method: 'POST',
      body: JSON.stringify({ ops: batch.map(mapOutboxToOp) }),
    })
    if (!resp.ok) throw new Error(`push failed ${resp.status}`)
    const data = await resp.json()
    // 成功的 op 移出 outbox；网络错误留在队列，服务端拒绝则阻断并等待用户处理。
    const byOpId = new Map(batch.map((item) => [item.op_id, item]))
    for (const result of data.results as Array<{
      op_id: string
      status: string
      new_rev?: number
      server_row?: Record<string, unknown>
      error?: { code?: string }
    }>) {
      if (['applied', 'merged'].includes(result.status)) {
        const op = byOpId.get(result.op_id)
        if (op) {
          // 服务端可能按业务唯一键改写行 id（setting 复用同 key 行），
          // 一律以 server_row 为准，否则本地会出现同 key 两行。
          const rowId = await this.alignServerRowId(op, result.server_row)
          if (typeof result.new_rev === 'number') {
            const key = syncKey(op.entity, rowId)
            this.knownRevs.set(key, Math.max(this.knownRevs.get(key) ?? 0, result.new_rev))
            const revisions = this.selfAckRevs.get(key) ?? new Set<number>()
            revisions.add(result.new_rev)
            this.selfAckRevs.set(key, revisions)
          }
        }
        await db.outbox.delete(result.op_id)
      } else if (['rejected', 'conflict'].includes(result.status)) {
        const row = await db.outbox.get(result.op_id)
        // 引用还没到服务端（同批父行排在后面）属于暂时性失败：留在队列里重试，
        // 不要阻断成需要用户手动处理的失败态。
        const retryable = result.error?.code?.startsWith('invalid_reference') === true
        if (row && !retryable) {
          await db.outbox.put({
            ...row,
            blocked: true,
            last_error: result.error?.code ?? result.status,
          })
        }
        if (!retryable) {
          this.state = reduceSyncState(this.state, {
            type: 'error',
            message: `同步失败：${result.error?.code ?? result.status}`,
          })
        }
      }
    }
    this.state.pending = await this.pendingCount()
    this.emit()
    await this.reconcileShadows()
  }

  /** 本地写：先乐观更新镜像，再生成 op 入 outbox。 */
  async localWrite(
    entity: string,
    id: string,
    set: Record<string, unknown>,
    baseRev: number,
    deleted?: boolean,
  ) {
    const table = tableOf(entity)
    if (!table) throw new Error(`unknown entity: ${entity}`)
    const current = await table.get(id)
    const effectiveBaseRev = Math.max(baseRev, this.knownRevs.get(syncKey(entity, id)) ?? 0)
    // 打戳用服务端时间轴：服务端按 updated_at 判字段级 LWW 胜负，
    // 客户端本地时钟偏差不能影响胜负。
    const stamp = this.clientStamp()
    const optimistic = {
      ...(current ?? {}),
      ...set,
      id,
      _rev: current?._rev ?? baseRev,
      _updated_at: stamp,
      _deleted_at:
        deleted === undefined ? current?._deleted_at ?? null : deleted ? new Date().toISOString() : null,
    }
    const op = {
      op_id: crypto.randomUUID(),
      entity,
      id,
      set,
      base_rev: effectiveBaseRev,
      ...(deleted === undefined ? {} : { deleted }),
      updated_at: stamp,
      created_at: new Date().toISOString(),
    }
    if (isLocalMode()) {
      await table.put(optimistic)
      this.state.pending = 0
      this.emit()
      return
    }
    await db.transaction('rw', table, db.outbox, async () => {
      await table.put(optimistic)
      await db.outbox.add(op)
    })
    this.state.pending = await this.pendingCount()
    this.emit()
    if (isLocalMode()) return
    // 本地事务完成即返回；网络同步在后台串行执行，不阻塞按钮和编辑器。
    this.scheduleSync(LOCAL_WRITE_SYNC_DELAY_MS, true)
  }

  /** 上传已压缩图片；失败时由调用方保留本地 blob，联网后重试。 */
  async uploadMedia(id: string, sha256: string, file: Blob, filename = 'image') {
    if (isLocalMode()) throw new Error('local mode does not upload media')
    const form = new FormData()
    form.append('id', id)
    form.append('sha256', sha256)
    form.append('file', file, filename)
    const resp = await fetch(`${this.baseUrl}/media`, {
      method: 'POST',
      body: form,
      headers: this.token ? { Authorization: `Bearer ${this.token}` } : {},
    })
    if (resp.status === 401) throw new AuthInvalidError('media token invalid')
    if (!resp.ok) throw new Error(`media upload failed ${resp.status}`)
    return (await resp.json()) as { id: string; url: string; deduped: boolean }
  }

  /** SSE 订阅 + 5 分钟兜底轮询。SSE 只负责触发合并后的增量同步。 */
  start() {
    if (isLocalMode()) {
      this.stop()
      return
    }
    if (this.eventSource) this.eventSource.close()
    const token = this.token
    this.eventSource = token
      ? new EventSource(`${this.baseUrl}/events?token=${encodeURIComponent(token)}`)
      : null
    if (this.eventSource) {
      this.eventSource.onopen = () => this.setOnline(true)
      // EventSource 断线会自动重连；短暂重连不等于整个服务离线。
      // 真正的 HTTP 同步失败由 pull() 统一判定并显示离线。
      this.eventSource.onerror = () => undefined
      // 服务端发的是命名事件（event: change），不会派发给 onmessage；
      // 只监听 onmessage 会让「另一台设备的改动」永远收不到（只剩 5 分钟兜底轮询）。
      this.eventSource.addEventListener('change', () => {
        this.scheduleSync(SSE_SYNC_DELAY_MS, false, true)
      })
      this.eventSource.addEventListener('hello', () => this.setOnline(true))
    }
    if (this.pollTimer) clearInterval(this.pollTimer)
    this.pollTimer = window.setInterval(() => this.scheduleSync(0, false, true), SYNC_POLL_INTERVAL_MS)
    this.stopWindowListeners()
    const onlineHandler = () => this.scheduleSync(0, false, true)
    const focusHandler = () => this.scheduleSync(0, false, true)
    this.windowHandlers.set('online', onlineHandler)
    this.windowHandlers.set('focus', focusHandler)
    window.addEventListener('online', onlineHandler)
    window.addEventListener('focus', focusHandler)
    if (token) this.scheduleSync(0)
  }

  stop() {
    this.eventSource?.close()
    this.eventSource = null
    if (this.pollTimer) clearInterval(this.pollTimer)
    this.pollTimer = null
    if (this.syncTimer) clearTimeout(this.syncTimer)
    this.syncTimer = null
    if (this.syncingTimer) clearTimeout(this.syncingTimer)
    this.syncingTimer = null
    this.syncQueued = false
    this.stopWindowListeners()
  }

  async syncNow() {
    if (isLocalMode() || !this.token) return
    this.scheduleSync(0)
    if (this.syncPromise) await this.syncPromise
  }

  private setOnline(on: boolean) {
    if (this.state.online === on && (!on || !this.state.authInvalid)) return
    this.state = reduceSyncState(this.state, { type: 'online', online: on })
    this.emit()
  }

  private stopWindowListeners() {
    for (const [event, handler] of this.windowHandlers) window.removeEventListener(event, handler)
    this.windowHandlers.clear()
  }

  private scheduleSync(delayMs: number, followUp = false, queueIfRunning = followUp) {
    if (isLocalMode() || !this.token) return
    if (this.syncPromise) {
      if (queueIfRunning) this.syncQueued = true
      return
    }
    this.syncQueued = true
    if (delayMs > 0) {
      if (this.syncTimer === null) {
        this.syncTimer = window.setTimeout(() => {
          this.syncTimer = null
          void this.drainSync()
        }, delayMs)
      }
      return
    }
    if (this.syncTimer !== null) {
      clearTimeout(this.syncTimer)
      this.syncTimer = null
    }
    void this.drainSync()
  }

  private async drainSync(): Promise<void> {
    if (this.syncPromise) return this.syncPromise
    if (!this.syncQueued) return
    this.syncQueued = false
    this.syncPromise = this.performSync().finally(() => {
      this.syncPromise = null
      if (this.syncQueued && this.syncTimer === null) void this.drainSync()
    })
    return this.syncPromise
  }

  private async performSync(): Promise<void> {
    this.beginSyncing()
    this.setOnline(navigator.onLine)
    if (this.state.lastError) {
      this.state = reduceSyncState(this.state, { type: 'error', message: null })
      this.emit()
    }
    try {
      await this.flush()
      await this.pullImpl()
      this.retryAttempt = 0
      this.setOnline(true)
    } catch (e) {
      if (e instanceof AuthInvalidError) {
        this.state = reduceSyncState(this.state, { type: 'authInvalid', invalid: true })
        this.emit()
        return
      }
      this.setOnline(false)
      this.state = reduceSyncState(this.state, {
        type: 'error',
        message: '网络暂时不可用，已保存到本机，稍后自动重试',
      })
      this.emit()
      this.retryAttempt += 1
      const delay = Math.min(
        SYNC_RETRY_MAX_MS,
        SYNC_RETRY_BASE_MS * (2 ** Math.min(this.retryAttempt - 1, 6)),
      )
      this.scheduleSync(delay, true)
    } finally {
      this.endSyncing()
    }
  }

  private beginSyncing() {
    if (this.syncingTimer !== null || this.state.syncing) return
    this.syncingTimer = window.setTimeout(() => {
      this.syncingTimer = null
      if (!this.state.syncing) {
        this.state = reduceSyncState(this.state, { type: 'syncing', syncing: true })
        this.emit()
      }
    }, 300)
  }

  private endSyncing() {
    if (this.syncingTimer !== null) {
      clearTimeout(this.syncingTimer)
      this.syncingTimer = null
    }
    if (this.state.syncing) {
      this.state = reduceSyncState(this.state, { type: 'syncing', syncing: false })
      this.emit()
    }
  }

  private async pendingCount(): Promise<number> {
    const rows = await db.outbox.toArray()
    return rows.filter((row) => !row.blocked).length
  }

  private async applySnapshot(snapshot: Record<string, Record<string, unknown>[]>) {
    const entities = [
      'term',
      'course',
      'course_slot',
      'timetable_override',
      'lesson_period',
      'todo',
      'media',
      'attachment',
      'setting',
    ] as const
    await db.transaction('rw', entities.map((e) => tableOf(e)), async () => {
      for (const entity of entities) {
        const table = tableOf(entity)
        await table.clear()
        const rows = (snapshot[entity] ?? []).map((r) => normalizeRow(r))
        if (rows.length) await table.bulkPut(rows)
      }
    })
  }

  private async applyChanges(changes: Array<[string, Record<string, unknown>]>): Promise<{ changes: SyncChange[]; deferred: boolean }> {
    const seen = new Set<string>()
    const tables: Table<Record<string, unknown>, string>[] = []
    const pending = new Set(
      (await db.outbox.toArray())
        .filter((item) => !item.blocked)
        .map((item) => syncKey(item.entity, item.id)),
    )
    const applied: SyncChange[] = []
    let deferred = false
    for (const [entity] of changes) {
      if (!seen.has(entity) && entity in ENTITY_TABLES) {
        seen.add(entity)
        tables.push(tableOf(entity) as unknown as Table<Record<string, unknown>, string>)
      }
    }
    if (tables.length === 0) return { changes: applied, deferred }
    await db.transaction('rw', [...tables, db.sync_shadow], async () => {
      for (const [entity, row] of changes) {
        if (!(entity in ENTITY_TABLES)) continue
        const table = tableOf(entity) as unknown as Table<Record<string, unknown>, string>
        const normalized = normalizeRow(row)
        const id = String(normalized.id)
        const key = syncKey(entity, id)
        const incomingRev = Number(normalized._rev ?? 0)
        const current = await table.get(id)
        if (pending.has(key)) {
          const previousShadow = await db.sync_shadow.get(key)
          if (!previousShadow || Number(previousShadow._rev ?? 0) < incomingRev) {
            await db.sync_shadow.put({
              ...normalized,
              key,
              entity,
            } as SyncShadowRow)
          }
          deferred = true
          continue
        }
        const selfEcho = this.consumeSelfAck(key, incomingRev)
        this.knownRevs.set(key, Math.max(this.knownRevs.get(key) ?? 0, incomingRev))
        if (current && Number(current._rev ?? 0) >= incomingRev) continue
        // 保留墓碑，恢复操作和回收站需要它；各视图自行过滤 _deleted_at。
        // media.blob 只存在本地（服务端 media 行没有该列），覆盖时保留，
        // 否则同步一遍就把离线可看的缩略图丢了；其余字段仍以服务端为准。
        const payload =
          entity === 'media' && current?.blob ? { ...normalized, blob: current.blob } : normalized
        await table.put(payload)
        await db.sync_shadow.delete(key)
        if (!selfEcho) {
          applied.push({
            entity,
            id,
            rev: incomingRev,
            deleted: Boolean(normalized._deleted_at),
          })
        }
      }
    })
    return { changes: applied, deferred }
  }

  private async reconcileShadows(): Promise<void> {
    const shadows = await db.sync_shadow.toArray()
    if (shadows.length === 0) return
    const pending = new Set(
      (await db.outbox.toArray())
        .filter((item) => !item.blocked)
        .map((item) => syncKey(item.entity, item.id)),
    )
    const applied: SyncChange[] = []
    for (const shadow of shadows) {
      if (pending.has(shadow.key) || !(shadow.entity in ENTITY_TABLES)) continue
      const table = tableOf(shadow.entity) as unknown as Table<Record<string, unknown>, string>
      const current = await table.get(shadow.id)
      if (!current || Number(current._rev ?? 0) < Number(shadow._rev ?? 0)) {
        const { key: _key, entity: _entity, ...normalized } = shadow
        await table.put(normalized as unknown as Record<string, unknown>)
        const rev = Number(shadow._rev ?? 0)
        this.knownRevs.set(shadow.key, Math.max(this.knownRevs.get(shadow.key) ?? 0, rev))
        if (!this.consumeSelfAck(shadow.key, rev)) {
          applied.push({
            entity: shadow.entity,
            id: shadow.id,
            rev,
            deleted: Boolean(shadow._deleted_at),
          })
        }
      }
      await db.sync_shadow.delete(shadow.key)
    }
    this.emitChanges(applied)
  }

  /** 服务端按业务唯一键改写了行 id 时，把本地行搬到服务端 id 下并返回新 id。 */
  private async alignServerRowId(
    op: { entity: string; id: string },
    serverRow?: Record<string, unknown>,
  ): Promise<string> {
    const serverId = serverRow ? String(serverRow.id ?? '') : ''
    if (!serverId || serverId === op.id) return op.id
    const table = tableOf(op.entity)
    if (!table) return op.id
    const local = await table.get(op.id)
    if (local) {
      // 同一个事务里改名：中途失败不会留下「同业务键两行」的中间态。
      await db.transaction('rw', table, async () => {
        await table.put({ ...local, ...normalizeRow(serverRow as Record<string, unknown>) })
        await table.delete(op.id)
      })
    }
    const oldKey = syncKey(op.entity, op.id)
    const newKey = syncKey(op.entity, serverId)
    const known = this.knownRevs.get(oldKey)
    this.knownRevs.delete(oldKey)
    if (known !== undefined) this.knownRevs.set(newKey, Math.max(known, this.knownRevs.get(newKey) ?? 0))
    const revisions = this.selfAckRevs.get(oldKey)
    this.selfAckRevs.delete(oldKey)
    if (revisions) this.selfAckRevs.set(newKey, revisions)
    return serverId
  }

  private consumeSelfAck(key: string, rev: number): boolean {
    const revisions = this.selfAckRevs.get(key)
    if (!revisions?.has(rev)) return false
    revisions.delete(rev)
    if (revisions.size === 0) this.selfAckRevs.delete(key)
    return true
  }
}

export function normalizeRow(raw: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {
    id: raw.id,
    _rev: raw.rev,
    _updated_at: raw.updated_at ?? null,
    _deleted_at: raw.deleted_at ?? null,
  }
  for (const [k, v] of Object.entries(raw)) {
    if (!['id', 'rev', 'updated_at', 'deleted_at'].includes(k)) out[k] = v
  }
  return out
}

const ENTITY_TABLES: Record<string, Table<Record<string, unknown>, string>> = {
  term: db.term as unknown as Table<Record<string, unknown>, string>,
  course: db.course as unknown as Table<Record<string, unknown>, string>,
  course_slot: db.course_slot as unknown as Table<Record<string, unknown>, string>,
  timetable_override: db.timetable_override as unknown as Table<Record<string, unknown>, string>,
  lesson_period: db.lesson_period as unknown as Table<Record<string, unknown>, string>,
  todo: db.todo as unknown as Table<Record<string, unknown>, string>,
  media: db.media as unknown as Table<Record<string, unknown>, string>,
  attachment: db.attachment as unknown as Table<Record<string, unknown>, string>,
  setting: db.setting as unknown as Table<Record<string, unknown>, string>,
}

function tableOf(entity: string): Table<Record<string, unknown>, string> {
  return ENTITY_TABLES[entity]
}

function syncKey(entity: string, id: string): string {
  return `${entity}:${id}`
}

export function mapOutboxToOp(o: {
  op_id: string
  entity: string
  id: string
  set: Record<string, unknown>
  base_rev: number
  deleted?: boolean
  updated_at?: string
}) {
  return {
    op_id: o.op_id,
    entity: o.entity,
    id: o.id,
    set: o.set,
    base_rev: o.base_rev,
    ...(o.deleted === undefined ? {} : { deleted: o.deleted }),
    ...(o.updated_at === undefined ? {} : { updated_at: o.updated_at }),
  }
}

export const sync = new SyncClient()

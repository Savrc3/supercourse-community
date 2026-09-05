/** 同步客户端：outbox 重试 + 增量拉取 + SSE 订阅 + 离线标记。 */

import type { Table } from 'dexie'

import { db } from '../../db/db'
import { getApiBase } from '../http'
import { isLocalMode } from '../connection'

const TOKEN_KEY = 'sc_token'
const CURSOR_KEY = 'sc_cursor'

export class AuthInvalidError extends Error {}

export interface SyncState {
  online: boolean
  pending: number
  lastSyncAt: number | null
  latestRev: number
  /** token 无效/未配对：应提示重新绑定而不是"离线"。 */
  authInvalid: boolean
}

/** 同步状态机的纯归约：对 state 做一次事件迁移。可单测。 */
export function reduceSyncState(
  state: SyncState,
  action:
    | { type: 'online'; online: boolean }
    | { type: 'pending'; pending: number }
    | { type: 'synced'; latestRev: number }
    | { type: 'authInvalid'; invalid: boolean },
): SyncState {
  switch (action.type) {
    case 'online':
      return { ...state, online: action.online, authInvalid: action.online ? false : state.authInvalid }
    case 'pending':
      return { ...state, pending: action.pending }
    case 'synced':
      return {
        ...state,
        latestRev: action.latestRev,
        lastSyncAt: Date.now(),
        online: true,
        authInvalid: false,
      }
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
  state: SyncState = {
    online: navigator.onLine,
    pending: 0,
    lastSyncAt: null,
    latestRev: 0,
    authInvalid: false,
  }
  private listeners = new Set<(s: SyncState) => void>()

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
  }

  setBaseUrl(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/+$/, '')
  }

  resetCursor() {
    this.cursor = 0
    localStorage.removeItem(CURSOR_KEY)
  }

  subscribe(fn: (s: SyncState) => void): () => void {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  private emit() {
    this.listeners.forEach((fn) => fn({ ...this.state }))
  }

  private readCursor(): number {
    return Number(localStorage.getItem(CURSOR_KEY) ?? 0)
  }

  private persistCursor(v: number) {
    this.cursor = v
    localStorage.setItem(CURSOR_KEY, String(v))
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
    this.persistCursor(data.latest_rev ?? 0)
    this.state.latestRev = data.latest_rev ?? 0
    this.state.lastSyncAt = Date.now()
    this.emit()
  }

  /** 增量拉取，落库并推进游标。 */
  async pull(): Promise<void> {
    if (isLocalMode()) return
    try {
      const resp = await this.request(`/sync/changes?since=${this.cursor}&limit=500`)
      if (!resp.ok) throw new Error(`changes failed ${resp.status}`)
      const data = await resp.json()
      if (data.full && data.snapshot) {
        await this.applySnapshot(data.snapshot)
      } else {
        await this.applyChanges(data.changes ?? [])
      }
      this.persistCursor(data.next_cursor ?? data.latest_rev ?? 0)
      this.state = reduceSyncState(this.state, {
        type: 'synced',
        latestRev: data.latest_rev ?? 0,
      })
      this.emit()
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
    const queue = await db.outbox.orderBy('created_at').toArray()
    if (queue.length === 0) return
    const batch = queue.slice(0, 100)
    const resp = await this.request('/sync/push', {
      method: 'POST',
      body: JSON.stringify({ ops: batch.map(mapOutboxToOp) }),
    })
    if (!resp.ok) throw new Error(`push failed ${resp.status}`)
    const data = await resp.json()
    // 成功的 op 移出 outbox，失败的保留待重试。
    for (const result of data.results as Array<{ op_id: string; status: string }>) {
      if (['applied', 'merged'].includes(result.status)) {
        await db.outbox.delete(result.op_id)
      }
    }
    this.state.pending = await db.outbox.count()
    this.emit()
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
    const optimistic = {
      ...(current ?? {}),
      ...set,
      id,
      _rev: current?._rev ?? baseRev,
      _updated_at: current?._updated_at ?? null,
      _deleted_at:
        deleted === undefined ? current?._deleted_at ?? null : deleted ? new Date().toISOString() : null,
    }
    const op = {
      op_id: crypto.randomUUID(),
      entity,
      id,
      set,
      base_rev: baseRev,
      ...(deleted === undefined ? {} : { deleted }),
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
    this.state.pending = await db.outbox.count()
    this.emit()
    if (isLocalMode()) return
    try {
      await this.flush()
      await this.pull()
    } catch (e) {
      // 离线或 token 无效时保留 outbox，等下次 flush。
      if (e instanceof AuthInvalidError) {
        this.state = reduceSyncState(this.state, { type: 'authInvalid', invalid: true })
      } else {
        this.setOnline(false)
      }
      this.emit()
    }
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

  /** SSE 订阅 + 30s 兜底轮询。断线时只靠轮询。 */
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
      this.eventSource.onmessage = (_e: MessageEvent<string>) => {
        void this.pull().catch(() => undefined)
      }
    }
    if (this.pollTimer) clearInterval(this.pollTimer)
    this.pollTimer = window.setInterval(() => void this.pull().catch(() => undefined), 30_000)
    ;['online', 'focus'].forEach((evt) =>
      window.addEventListener(evt, () => void this.syncNow()),
    )
    if (token) void this.syncNow()
  }

  stop() {
    this.eventSource?.close()
    this.eventSource = null
    if (this.pollTimer) clearInterval(this.pollTimer)
    this.pollTimer = null
  }

  async syncNow() {
    if (isLocalMode() || !this.token) return
    this.setOnline(navigator.onLine)
    try {
      await this.flush()
      await this.pull()
      this.setOnline(true)
    } catch (e) {
      if (e instanceof AuthInvalidError) {
        this.state = reduceSyncState(this.state, { type: 'authInvalid', invalid: true })
        this.emit()
      } else {
        this.setOnline(false)
      }
    }
  }

  private setOnline(on: boolean) {
    this.state = reduceSyncState(this.state, { type: 'online', online: on })
    this.emit()
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

  private async applyChanges(changes: Array<[string, Record<string, unknown>]>) {
    const seen = new Set<string>()
    const tables: Table<Record<string, unknown>, string>[] = []
    for (const [entity] of changes) {
      if (!seen.has(entity) && entity in ENTITY_TABLES) {
        seen.add(entity)
        tables.push(tableOf(entity) as unknown as Table<Record<string, unknown>, string>)
      }
    }
    if (tables.length === 0) return
    await db.transaction('rw', tables, async () => {
      for (const [entity, row] of changes) {
        if (!(entity in ENTITY_TABLES)) continue
        const table = tableOf(entity) as unknown as Table<Record<string, unknown>, string>
        const normalized = normalizeRow(row)
        // 保留墓碑，恢复操作和回收站需要它；各视图自行过滤 _deleted_at。
        await table.put(normalized)
      }
    })
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

export function mapOutboxToOp(o: {
  op_id: string
  entity: string
  id: string
  set: Record<string, unknown>
  base_rev: number
  deleted?: boolean
}) {
  return {
    op_id: o.op_id,
    entity: o.entity,
    id: o.id,
    set: o.set,
    base_rev: o.base_rev,
    ...(o.deleted === undefined ? {} : { deleted: o.deleted }),
  }
}

export const sync = new SyncClient()

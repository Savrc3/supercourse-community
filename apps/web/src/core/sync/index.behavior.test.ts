import { beforeEach, describe, expect, it, vi } from 'vitest'

type Row = Record<string, unknown> & { id: string }

const mock = vi.hoisted(() => {
  const rows = new Map<string, Row>()
  const outboxRows = new Map<string, Record<string, unknown>>()
  const shadows = new Map<string, Row & { key: string }>()
  const makeTable = () => ({
    get: vi.fn(async (id: string) => rows.get(id)),
    put: vi.fn(async (row: Row) => { rows.set(row.id, { ...row }) }),
    delete: vi.fn(async (id: string) => { rows.delete(id) }),
    update: vi.fn(async (id: string, changes: Record<string, unknown>) => {
      rows.set(id, { ...(rows.get(id) ?? { id }), ...changes })
    }),
    filter: vi.fn(() => ({ toArray: async () => [...rows.values()] })),
    toArray: vi.fn(async () => [...rows.values()]),
    clear: vi.fn(async () => { rows.clear() }),
    bulkPut: vi.fn(async (items: Row[]) => { items.forEach((row) => rows.set(row.id, { ...row })) }),
  })
  const table = makeTable()
  const outbox = {
    add: vi.fn(async (row: Record<string, unknown>) => { outboxRows.set(String(row.op_id), { ...row }) }),
    get: vi.fn(async (id: string) => outboxRows.get(id)),
    put: vi.fn(async (row: Record<string, unknown>) => { outboxRows.set(String(row.op_id), { ...row }) }),
    delete: vi.fn(async (id: string) => { outboxRows.delete(id) }),
    count: vi.fn(async () => outboxRows.size),
    toArray: vi.fn(async () => [...outboxRows.values()]),
    orderBy: vi.fn(() => ({ toArray: async () => [...outboxRows.values()] })),
  }
  const fakeDb = {
    term: table,
    course: table,
    course_slot: table,
    timetable_override: table,
    lesson_period: table,
    todo: table,
    media: table,
    attachment: table,
    setting: table,
    sync_shadow: {
      get: vi.fn(async (key: string) => shadows.get(key)),
      put: vi.fn(async (row: Row & { key: string }) => { shadows.set(row.key, { ...row }) }),
      delete: vi.fn(async (key: string) => { shadows.delete(key) }),
      toArray: vi.fn(async () => [...shadows.values()]),
    },
    outbox,
    transaction: vi.fn(async (...args: unknown[]) => {
      const callback = args.at(-1) as () => Promise<unknown>
      return callback()
    }),
  }
  return { rows, outboxRows, shadows, table, outbox, fakeDb }
})

vi.mock('../../db/db', () => ({ db: mock.fakeDb }))
vi.mock('../connection', () => ({ isLocalMode: () => false }))
vi.mock('../http', () => ({ getApiBase: () => '/api' }))

const { SyncClient, SYNC_POLL_INTERVAL_MS, mapOutboxToOp } = await import('./index')

describe('同步体验回归', () => {
  beforeEach(() => {
    mock.rows.clear()
    mock.outboxRows.clear()
    mock.shadows.clear()
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('网络请求卡住时，本地删除仍立即完成并保留待同步操作', async () => {
    const client = new SyncClient('/api')
    client.setToken('test-token')
    mock.rows.set('todo-1', { id: 'todo-1', _rev: 1, _deleted_at: null, title: '待删除' })
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)))

    const result = await Promise.race([
      client.localWrite('todo', 'todo-1', {}, 1, true).then(() => 'local-complete'),
      new Promise((resolve) => setTimeout(() => resolve('network-blocked'), 100)),
    ])

    expect(result).toBe('local-complete')
    expect(mock.rows.get('todo-1')?._deleted_at).not.toBeNull()
    expect(mock.outboxRows.size).toBe(1)
    client.stop()
  })

  it('远端变更不会覆盖存在待同步操作的本地行', async () => {
    const client = new SyncClient('/api') as unknown as {
      applyChanges: (changes: Array<[string, Record<string, unknown>]>) => Promise<{ deferred: boolean }>
    }
    mock.rows.set('todo-1', { id: 'todo-1', _rev: 1, _deleted_at: null, title: '本地修改' })
    mock.outboxRows.set('op-1', { op_id: 'op-1', entity: 'todo', id: 'todo-1', set: { title: '本地修改' }, base_rev: 1 })

    const result = await client.applyChanges([
      ['todo', { id: 'todo-1', rev: 2, deleted_at: null, title: '远端旧修改' }],
    ])

    expect(result.deferred).toBe(true)
    expect(mock.rows.get('todo-1')?.title).toBe('本地修改')
  })

  it('媒体行从服务端回显时保留本地 blob', async () => {
    const client = new SyncClient('/api') as unknown as {
      applyChanges: (changes: Array<[string, Record<string, unknown>]>) => Promise<{ deferred: boolean }>
    }
    const blob = new Blob(['x'])
    mock.rows.set('media-1', { id: 'media-1', _rev: 1, _deleted_at: null, uploaded: 0, blob })

    await client.applyChanges([
      ['media', { id: 'media-1', rev: 5, deleted_at: null, uploaded: 1, ext: 'jpg' }],
    ])

    const stored = mock.rows.get('media-1')
    expect(stored?._rev).toBe(5)
    expect(stored?.uploaded).toBe(1)
    expect(stored?.blob).toBe(blob)
  })

  it('两个并发同步请求合并为一次实际拉取', async () => {
    const client = new SyncClient('/api')
    client.setToken('test-token')
    let release!: () => void
    const response = new Promise<Response>((resolve) => {
      release = () => resolve(new Response(JSON.stringify({ changes: [], latest_rev: 0, next_cursor: 0 }), { status: 200 }))
    })
    const fetchMock = vi.fn(() => response)
    vi.stubGlobal('fetch', fetchMock)

    const first = client.syncNow()
    const second = client.syncNow()
    release()
    await Promise.all([first, second])

    expect(fetchMock).toHaveBeenCalledTimes(1)
    client.stop()
  })

  it('本机刚提交的服务器回显不会再次通知页面刷新', async () => {
    const client = new SyncClient('/api')
    client.setToken('test-token')
    mock.rows.set('todo-1', { id: 'todo-1', _rev: 0, _deleted_at: null, title: '本地修改' })
    mock.outboxRows.set('op-1', {
      op_id: 'op-1',
      entity: 'todo',
      id: 'todo-1',
      set: { title: '本地修改' },
      base_rev: 0,
      created_at: 'now',
    })
    const changes: unknown[] = []
    client.subscribeChanges((items) => changes.push(items))
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        results: [{ op_id: 'op-1', status: 'applied', new_rev: 1 }],
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        changes: [['todo', { id: 'todo-1', rev: 1, deleted_at: null, title: '本地修改' }]],
        latest_rev: 1,
        next_cursor: 1,
      }), { status: 200 })))

    await client.syncNow()

    expect(mock.rows.get('todo-1')?._rev).toBe(1)
    expect(changes).toHaveLength(0)
    client.stop()
  })

  it('其他设备的服务器变更仍会通知对应页面刷新', async () => {
    const client = new SyncClient('/api')
    client.setToken('test-token')
    const changes: unknown[] = []
    client.subscribeChanges((items) => changes.push(items))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({
      changes: [['todo', { id: 'todo-remote', rev: 2, deleted_at: null, title: '其他设备修改' }]],
      latest_rev: 2,
      next_cursor: 2,
    }), { status: 200 })))

    await client.syncNow()

    expect(changes).toHaveLength(1)
    expect(mock.rows.get('todo-remote')?.title).toBe('其他设备修改')
    client.stop()
  })

  it('兜底轮询间隔为五分钟', () => {
    expect(SYNC_POLL_INTERVAL_MS).toBe(5 * 60 * 1000)
  })

  it('服务端拒绝的操作会阻断重试并保留错误状态', async () => {
    const client = new SyncClient('/api')
    client.setToken('test-token')
    mock.outboxRows.set('op-1', {
      op_id: 'op-1', entity: 'todo', id: 'todo-1', set: {}, base_rev: 1, created_at: 'now',
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      results: [{ op_id: 'op-1', status: 'rejected', error: { code: 'unknown_field' } }],
    }), { status: 200 })))

    await client.flush()

    expect(mock.outboxRows.get('op-1')?.blocked).toBe(true)
    expect(client.state.pending).toBe(0)
    expect(client.state.lastError).toContain('unknown_field')
  })

  it('SSE 订阅服务端实际发送的命名事件 change', () => {
    const listeners: string[] = []
    class FakeEventSource {
      url: string
      onopen: (() => void) | null = null
      onerror: (() => void) | null = null
      onmessage: ((event: MessageEvent<string>) => void) | null = null
      constructor(url: string) {
        this.url = url
      }
      addEventListener(type: string) {
        listeners.push(type)
      }
      close() {}
    }
    vi.stubGlobal('EventSource', FakeEventSource)
    const client = new SyncClient('/api')
    client.setToken('test-token')
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ changes: [], latest_rev: 0, next_cursor: 0 }),
      { status: 200 },
    )))

    client.start()

    // 服务端发的是 event: change，只会派发给 addEventListener('change')；
    // 只挂 onmessage 会永远收不到其他设备的改动。
    expect(listeners).toContain('change')
    expect(client.state.online).toBe(true)
    client.stop()
  })

  it('服务端按业务唯一键改写行 id 时本地行跟着搬家', async () => {
    const client = new SyncClient('/api')
    client.setToken('test-token')
    mock.rows.set('local-setting', { id: 'local-setting', _rev: 0, key: 'reminder.config', value: '{}' })
    mock.outboxRows.set('op-1', {
      op_id: 'op-1', entity: 'setting', id: 'local-setting',
      set: { key: 'reminder.config', value: '{}' }, base_rev: 0, created_at: 'now',
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      results: [{
        op_id: 'op-1',
        status: 'applied',
        new_rev: 7,
        server_row: { id: 'server-setting', rev: 7, updated_at: 'u', deleted_at: null, key: 'reminder.config', value: '{}' },
      }],
    }), { status: 200 })))

    await client.flush()

    expect(mock.rows.has('local-setting')).toBe(false)
    expect(mock.rows.get('server-setting')?._rev).toBe(7)
    expect(mock.outboxRows.size).toBe(0)
    client.stop()
  })

  it('引用还没到服务端的 op 保持可重试，不进入阻断态', async () => {
    const client = new SyncClient('/api')
    client.setToken('test-token')
    mock.outboxRows.set('op-1', {
      op_id: 'op-1', entity: 'course_slot', id: 'slot-1', set: {}, base_rev: 0, created_at: 'now',
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      results: [{ op_id: 'op-1', status: 'rejected', error: { code: 'invalid_reference:course_id' } }],
    }), { status: 200 })))

    await client.flush()

    expect(mock.outboxRows.get('op-1')?.blocked).toBeUndefined()
    expect(client.state.pending).toBe(1)
    expect(client.state.lastError).toBeNull()
    client.stop()
  })

  it('本地写入的 op 带服务端时间轴的 updated_at', async () => {
    const client = new SyncClient('/api')
    client.setToken('test-token')
    const serverTime = new Date(Date.now() + 3600_000).toISOString()
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      changes: [], latest_rev: 0, next_cursor: 0, server_time: serverTime,
    }), { status: 200 })))

    await client.syncNow()
    await client.localWrite('todo', 'todo-1', { title: '写作业' }, 0)

    const op = [...mock.outboxRows.values()][0] as Record<string, unknown>
    const stamp = String(op.updated_at)
    expect(Number.isNaN(Date.parse(stamp))).toBe(false)
    // 本地时钟比服务端慢 1 小时，打戳必须按服务端时间校正
    expect(Math.abs(Date.parse(stamp) - Date.parse(serverTime))).toBeLessThan(5000)
    expect(mapOutboxToOp(op as never).updated_at).toBe(stamp)
    client.stop()
  })
})

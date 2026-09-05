import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  todos: [] as Record<string, unknown>[],
  db: {
    todo: { toArray: vi.fn(async () => mocks.todos) },
    course: { toArray: vi.fn(async () => []) },
  },
  subscribe: vi.fn().mockReturnValue(() => undefined),
}))

vi.mock('../../core/sync', () => ({ sync: mocks }))
vi.mock('../../db/db', () => ({ db: mocks.db }))

import TimelineView from './TimelineView.vue'

function dateFromToday(days: number): string {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function makeTodo(id: string, dueAt: string | null) {
  return {
    id,
    _deleted_at: null,
    course_id: null,
    title: id,
    due_at: dueAt,
    due_all_day: 1,
    status: '0',
    priority: 1,
    tags: '[]',
    sort_order: 0,
  }
}

describe('TimelineView 时间分组', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-07T08:00:00+08:00'))
    mocks.todos.splice(0, mocks.todos.length,
      makeTodo('逾期', dateFromToday(-1)),
      makeTodo('今天', dateFromToday(0)),
      makeTodo('明天', dateFromToday(1)),
      makeTodo('本周', dateFromToday(2)),
      makeTodo('以后', dateFromToday(14)),
      makeTodo('无时间', null),
    )
  })

  afterEach(() => vi.useRealTimers())

  it('始终展示六个时间层级，即使某个层级为空', async () => {
    const wrapper = mount(TimelineView, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    const text = wrapper.findAll('h2').map((heading) => heading.text())
    expect(text).toEqual(expect.arrayContaining(['逾期 1', '今天 1', '明天 1', '本周 1', '以后 1', '无时间 1']))
  })
})

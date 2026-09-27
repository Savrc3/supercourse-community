import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => {
  const state = {
    todos: [] as Record<string, unknown>[],
    localWrite: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn().mockReturnValue(() => undefined),
    subscribeChanges: vi.fn().mockReturnValue(() => undefined),
    route: { query: {} as Record<string, string> },
    router: { replace: vi.fn().mockResolvedValue(undefined) },
  }
  return {
    ...state,
    db: {
      todo: { toArray: vi.fn(async () => state.todos) },
      term: { toArray: vi.fn(async () => []) },
      course: { toArray: vi.fn(async () => []) },
    },
  }
})

vi.mock('../../core/sync', () => ({ sync: mocks }))
vi.mock('../../db/db', () => ({ db: mocks.db }))
vi.mock('vue-router', () => ({ useRoute: () => mocks.route, useRouter: () => mocks.router }))

import TodoView from './TodoView.vue'

function todo(overrides: Record<string, unknown> = {}) {
  return {
    id: 'todo-1',
    _rev: 1,
    _updated_at: null,
    _deleted_at: null,
    course_id: null,
    kind: 'todo',
    title: '原待办',
    body: '{}',
    body_text: '',
    due_at: null,
    start_at: null,
    due_all_day: 1,
    repeat: null,
    status: '0',
    done_at: null,
    priority: 1,
    tags: '[]',
    remind_mode: 'inherit',
    remind_offsets: null,
    sort_order: 0,
    created_at: '2026-09-04T00:00:00',
    ...overrides,
  }
}

describe('TodoView 待办操作', () => {
  beforeEach(() => {
    mocks.todos.length = 0
    mocks.localWrite.mockClear()
    mocks.subscribe.mockClear()
    mocks.db.todo.toArray.mockClear()
    mocks.db.term.toArray.mockClear()
    mocks.db.course.toArray.mockClear()
    mocks.route.query = {}
    mocks.router.replace.mockClear()
  })

  it('快速新增只要求标题，并保留可选课程与截止时间', async () => {
    const wrapper = mount(TodoView, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    await wrapper.get('.empty-card .ghost-btn').trigger('click')
    await wrapper.get('input[placeholder="如：完成高数第三章习题"]').setValue('交实验报告')
    await wrapper.get('input[type="date"]').setValue('2026-09-08')
    await wrapper.get('input[type="checkbox"]').setValue(false)
    await wrapper.get('input[type="time"]').setValue('14:30')
    await wrapper.get('form').trigger('submit')

    expect(mocks.localWrite).toHaveBeenCalledWith(
      'todo',
      expect.any(String),
      expect.objectContaining({
        title: '交实验报告',
        course_id: null,
        due_at: '2026-09-08T14:30',
        due_all_day: 0,
        status: '0',
        priority: 1,
        tags: '[]',
        remind_mode: 'inherit',
      }),
      0,
    )
  })

  it('完成和删除都通过 localWrite 落库，编辑留在详情页', async () => {
    mocks.todos.push(todo())
    const wrapper = mount(TodoView, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    await wrapper.get('button[aria-label="完成：原待办"]').trigger('click')
    expect(mocks.localWrite).toHaveBeenCalledWith(
      'todo',
      'todo-1',
      expect.objectContaining({ status: '1', done_at: expect.any(String) }),
      1,
    )

    mocks.localWrite.mockClear()
    vi.stubGlobal('confirm', vi.fn(() => true))
    await wrapper.get('button[aria-label="删除：原待办"]').trigger('click')
    expect(mocks.localWrite).toHaveBeenCalledWith('todo', 'todo-1', {}, 1, true)
    vi.unstubAllGlobals()
  })

  it('本地操作不会再次整表读取造成列表刷新', async () => {
    mocks.todos.push(todo())
    const wrapper = mount(TodoView, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()
    mocks.db.todo.toArray.mockClear()
    mocks.db.term.toArray.mockClear()
    mocks.db.course.toArray.mockClear()

    await wrapper.get('button[aria-label="完成：原待办"]').trigger('click')

    expect(mocks.db.todo.toArray).not.toHaveBeenCalled()
    expect(mocks.db.term.toArray).not.toHaveBeenCalled()
    expect(mocks.db.course.toArray).not.toHaveBeenCalled()
    expect(wrapper.get('.completed-section summary').text()).toContain('已完成（1）')
    wrapper.unmount()
  })

  it('二元状态的折叠区只显示已完成', async () => {
    mocks.todos.push(todo({ status: '1', done_at: '2026-09-04T10:00:00' }))
    const wrapper = mount(TodoView, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    expect(wrapper.get('.completed-section summary').text()).toBe('已完成（1）')
  })

  it('待办页能切换清单和按日期，并保留旧时间线入口', async () => {
    const wrapper = mount(TodoView, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    await wrapper.get('.todo-view-tabs button:nth-child(2)').trigger('click')
    expect(mocks.router.replace).toHaveBeenCalledWith({ path: '/todo', query: { view: 'date' } })
    wrapper.unmount()
  })
})

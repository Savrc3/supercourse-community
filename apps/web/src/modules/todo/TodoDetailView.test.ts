import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => {
  const row = {
    id: 'todo-1',
    _rev: 3,
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
  }
  return {
    row,
    localWrite: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn().mockReturnValue(() => undefined),
    push: vi.fn().mockResolvedValue(undefined),
    db: {
      todo: { get: vi.fn(async () => row) },
      term: { toArray: vi.fn(async () => []) },
      course: { toArray: vi.fn(async () => []) },
      media: {
        toArray: vi.fn(async () => []),
        get: vi.fn(async () => undefined),
        filter: vi.fn(() => ({ toArray: vi.fn(async () => []) })),
        put: vi.fn(async () => undefined),
        update: vi.fn(async () => undefined),
      },
    },
  }
})

vi.mock('../../core/sync', () => ({ sync: mocks }))
vi.mock('../../db/db', () => ({ db: mocks.db }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: 'todo-1' } }),
  useRouter: () => ({ push: mocks.push }),
}))

import TodoDetailView from './TodoDetailView.vue'

describe('TodoDetailView 待办详情', () => {
  beforeEach(() => {
    mocks.localWrite.mockClear()
    mocks.push.mockClear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('加载正文和元数据，并在修改后自动保存', async () => {
    const wrapper = mount(TodoDetailView, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    const title = wrapper.get('input[placeholder="如：完成高数第三章习题"]')
    await title.setValue('修改后的待办')
    await vi.advanceTimersByTimeAsync(800)

    expect(mocks.localWrite).toHaveBeenCalledWith(
      'todo',
      'todo-1',
      expect.objectContaining({
        title: '修改后的待办',
        body: expect.stringContaining('"type":"doc"'),
        body_text: '',
      }),
      3,
    )
    expect(wrapper.get('.save-state').text()).toContain('已保存')
    wrapper.unmount()
  })

  it('详情页可以切换二元完成状态', async () => {
    const wrapper = mount(TodoDetailView, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()
    await wrapper.get('.done-toggle').trigger('click')
    await vi.advanceTimersByTimeAsync(800)

    expect(mocks.localWrite).toHaveBeenCalledWith(
      'todo',
      'todo-1',
      expect.objectContaining({ status: '1', done_at: expect.any(String) }),
      3,
    )
    wrapper.unmount()
  })
})

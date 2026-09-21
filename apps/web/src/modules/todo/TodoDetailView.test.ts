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
  const result = {
    row,
    localWrite: vi.fn().mockResolvedValue(undefined),
    uploadMedia: vi.fn().mockResolvedValue({ id: 'media-1', url: '/api/media/media-1', deduped: false }),
    compressImage: vi.fn(async () => ({
      blob: new Blob(['image'], { type: 'image/jpeg' }),
      width: 1,
      height: 1,
      mime: 'image/jpeg',
      ext: 'jpg',
    })),
    sha256: vi.fn(async () => 'a'.repeat(64)),
    onChanges: null as ((changes: Array<{ entity: string; id: string; rev: number; deleted: boolean }>) => void) | null,
    subscribeChanges: vi.fn((handler: (changes: Array<{ entity: string; id: string; rev: number; deleted: boolean }>) => void) => {
      result.onChanges = handler
      return () => undefined
    }),
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
  return result
})

vi.mock('./media', () => ({
  compressImage: mocks.compressImage,
  sha256: mocks.sha256,
}))

vi.mock('../../core/connection', () => ({
  defaultRemoteApiBase: () => '/api',
  getConnectionMode: () => 'remote',
  getConnectionProfile: () => ({ mode: 'remote', serverUrl: '/api' }),
  isLocalMode: () => false,
  isSafeRemoteUrl: () => true,
  setConnectionProfile: vi.fn(),
  shouldShowSetup: () => false,
}))

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
    mocks.uploadMedia.mockClear()
    mocks.compressImage.mockClear()
    mocks.sha256.mockClear()
    mocks.push.mockClear()
    mocks.onChanges = null
    mocks.db.todo.get.mockClear()
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

  it('自定义提前量：切换到自定义后选中的提前量写进 remind_offsets', async () => {
    const wrapper = mount(TodoDetailView, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()
    expect(wrapper.findAll('.preset-chip')).toHaveLength(0)

    const custom = wrapper.findAll('.reminder-mode input').find((input) => (input.element as HTMLInputElement).value === 'custom')
    expect(custom).toBeDefined()
    await custom!.setValue()
    await vi.advanceTimersByTimeAsync(800)
    expect(wrapper.findAll('.preset-chip')).toHaveLength(7)
    expect(wrapper.get('.field-hint').text()).toContain('未选择提前量')

    const chip = wrapper.findAll('.preset-chip').find((item) => item.text().includes('1 小时'))!
    await chip.trigger('click')
    await vi.advanceTimersByTimeAsync(800)
    expect(mocks.localWrite).toHaveBeenLastCalledWith(
      'todo',
      'todo-1',
      expect.objectContaining({ remind_mode: 'custom', remind_offsets: '["-PT1H"]' }),
      3,
    )
    expect(wrapper.get('.field-hint').text()).toContain('1 小时')

    // 再点一次取消选中：模式仍是自定义，但提前量清空（等同退回全局默认）
    await chip.trigger('click')
    await vi.advanceTimersByTimeAsync(800)
    expect(mocks.localWrite).toHaveBeenLastCalledWith(
      'todo',
      'todo-1',
      expect.objectContaining({ remind_mode: 'custom', remind_offsets: null }),
      3,
    )
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

  it('可以输入 Markdown 源码并自动保存为富文本 JSON', async () => {
    const wrapper = mount(TodoDetailView, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()
    await wrapper.get('button[aria-label="Markdown源码"]').trigger('click')
    const source = wrapper.get('textarea[aria-label="Markdown源码"]')
    const markdown = '# 新标题\n\n- [ ] 待完成\n  - 子项'
    await source.setValue(markdown)
    await vi.advanceTimersByTimeAsync(800)

    expect(mocks.localWrite).toHaveBeenCalledWith(
      'todo',
      'todo-1',
      expect.objectContaining({
        body: expect.stringContaining('"type":"heading"'),
        body_text: expect.stringContaining('新标题'),
      }),
      3,
    )
    expect(wrapper.get('button[aria-label="预览 Markdown"]').attributes('title')).toBe('切回格式预览')
    await wrapper.get('button[aria-label="预览 Markdown"]').trigger('click')
    expect(wrapper.find('textarea[aria-label="Markdown源码"]').exists()).toBe(false)
    expect(wrapper.find('.ProseMirror h1').text()).toBe('新标题')
    expect(wrapper.find('.ProseMirror ul[data-type="taskList"]').exists()).toBe(true)
    expect(wrapper.get('.ProseMirror').text()).toContain('新标题')
    expect(wrapper.get('.ProseMirror').text()).not.toContain('# 新标题')
    await wrapper.get('button[aria-label="Markdown源码"]').trigger('click')
    expect((wrapper.get('textarea[aria-label="Markdown源码"]').element as HTMLTextAreaElement).value).toBe(markdown)
    wrapper.unmount()
  })

  it('进入 Markdown 源码编辑后，远端同步不会退出源码模式或重置光标', async () => {
    const wrapper = mount(TodoDetailView, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()
    await wrapper.get('button[aria-label="Markdown源码"]').trigger('click')

    mocks.onChanges?.([{ entity: 'todo', id: 'todo-1', rev: 4, deleted: false }])
    await vi.advanceTimersByTimeAsync(200)

    expect(wrapper.find('textarea[aria-label="Markdown源码"]').exists()).toBe(true)
    expect(mocks.db.todo.get).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('手机端上传成功后继续使用本地图片地址，不把相对 API 地址直接交给编辑器', async () => {
    const mediaId = '11111111-1111-4111-8111-111111111111'
    const originalCreateObjectURL = URL.createObjectURL
    const createObjectURL = vi.fn(() => 'blob:local-image')
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, writable: true, value: createObjectURL })
    const randomUUID = vi.spyOn(crypto, 'randomUUID').mockReturnValue(mediaId)
    const wrapper = mount(TodoDetailView, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    const input = wrapper.get('input[type="file"]')
    const file = new File(['source'], 'photo.jpg', { type: 'image/jpeg' })
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change')
    await flushPromises()

    expect(mocks.uploadMedia).toHaveBeenCalledWith(mediaId, 'a'.repeat(64), expect.any(Blob), 'photo.jpg')
    expect(wrapper.get('.ProseMirror img').attributes('src')).toBe('blob:local-image')
    await vi.advanceTimersByTimeAsync(800)
    expect(mocks.localWrite).toHaveBeenCalledWith(
      'todo',
      'todo-1',
      expect.objectContaining({ body: expect.stringContaining(`media://${mediaId}`) }),
      3,
    )
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, writable: true, value: originalCreateObjectURL })
    randomUUID.mockRestore()
    wrapper.unmount()
  })
})

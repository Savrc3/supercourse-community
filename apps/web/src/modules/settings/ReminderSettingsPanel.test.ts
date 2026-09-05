import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  settingFirst: vi.fn(async () => undefined),
  todos: vi.fn(async () => []),
  localWrite: vi.fn(async () => undefined),
}))

vi.mock('../../db/db', () => ({
  db: {
    setting: { where: () => ({ equals: () => ({ first: mocks.settingFirst }) }) },
    todo: { toArray: mocks.todos },
  },
}))
vi.mock('../../core/sync', () => ({ sync: { token: '', localWrite: mocks.localWrite } }))
vi.mock('../../core/notifications', () => ({
  requestLocalNotificationPermission: vi.fn(async () => 'granted'),
}))

import ReminderSettingsPanel from './ReminderSettingsPanel.vue'

describe('ReminderSettingsPanel', () => {
  beforeEach(() => {
    mocks.settingFirst.mockClear()
    mocks.todos.mockClear()
    localStorage.clear()
    vi.stubGlobal('fetch', vi.fn())
  })

  it('预览没有可用待办时也要给出明确反馈', async () => {
    const wrapper = mount(ReminderSettingsPanel)
    await flushPromises()

    const previewButton = wrapper.findAll('button').find((button) => button.text() === '预览系统通知')
    expect(previewButton).toBeDefined()
    await previewButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('当前没有可预览的待办提醒')
  })

  it('点击 QQ 后立即显示测试中状态', async () => {
    localStorage.setItem('sc_connection_profile', JSON.stringify({ mode: 'remote', serverUrl: 'http://localhost:8090/api' }))
    vi.mocked(fetch).mockReturnValue(new Promise(() => undefined))
    const wrapper = mount(ReminderSettingsPanel)
    await flushPromises()

    const qqButton = wrapper.findAll('button').find((button) => button.text() === '测试 QQ')
    expect(qqButton).toBeDefined()
    await qqButton!.trigger('click')

    expect(wrapper.text()).toContain('测试中…')
  })
})

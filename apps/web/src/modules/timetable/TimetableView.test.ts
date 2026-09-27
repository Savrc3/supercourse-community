import { flushPromises, mount } from '@vue/test-utils'
import { nextTick, reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  terms: [] as Record<string, unknown>[],
  courses: [] as Record<string, unknown>[],
  slots: [] as Record<string, unknown>[],
  periods: [] as Record<string, unknown>[],
  overrides: [] as Record<string, unknown>[],
  appStore: { mobileView: 'week' as 'day' | 'week', selectedTermId: null as string | null },
  localWrite: vi.fn().mockResolvedValue(undefined),
  subscribeChanges: vi.fn().mockReturnValue(() => undefined),
  subscribe: vi.fn().mockReturnValue(() => undefined),
}))

vi.mock('../../core/sync', () => ({ sync: mocks }))
vi.mock('../../core/connection', () => ({ isLocalMode: () => true }))
vi.mock('../../db/db', () => ({
  db: {
    term: { toArray: vi.fn(async () => mocks.terms) },
    course: { toArray: vi.fn(async () => mocks.courses) },
    course_slot: { toArray: vi.fn(async () => mocks.slots) },
    lesson_period: { toArray: vi.fn(async () => mocks.periods) },
    timetable_override: { toArray: vi.fn(async () => mocks.overrides) },
  },
}))
vi.mock('../../stores/app', () => ({ useAppStore: () => mocks.appStore }))

import TimetableView from './TimetableView.vue'

function dispatchPointer(target: Element, type: 'pointerdown' | 'pointerup', x: number, y: number) {
  const event = new Event(type, { bubbles: true })
  Object.defineProperties(event, {
    clientX: { value: x },
    clientY: { value: y },
  })
  target.dispatchEvent(event)
}

describe('TimetableView 周视图布局', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-21T12:00:00'))
    mocks.terms.length = 0
    mocks.courses.length = 0
    mocks.slots.length = 0
    mocks.periods.length = 0
    mocks.overrides.length = 0
    mocks.appStore = reactive({ mobileView: 'week', selectedTermId: null })
    mocks.localWrite.mockClear()
    mocks.subscribe.mockClear()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('周视图直接承载完整七天网格，不依赖横向滚动容器', async () => {
    mocks.terms.push({
      id: 'term-1',
      _rev: 1,
      _updated_at: null,
      _deleted_at: null,
      name: '2026-2027-1',
      label: null,
      start_date: '2026-08-31',
      weeks_total: 20,
      is_current: 1,
      archived_at: null,
    })

    const wrapper = mount(TimetableView)
    await flushPromises()

    expect(wrapper.find('.week-grid').exists()).toBe(true)
    expect(wrapper.find('.week-scroll').exists()).toBe(false)
    wrapper.unmount()
  })

  it('日视图把选中日期和真实今天分开标记', async () => {
    mocks.terms.push({
      id: 'term-1',
      _rev: 1,
      _updated_at: null,
      _deleted_at: null,
      name: '2026-2027-1',
      label: null,
      start_date: '2026-08-31',
      weeks_total: 20,
      is_current: 1,
      archived_at: null,
    })

    const wrapper = mount(TimetableView)
    await flushPromises()
    await wrapper.find('.icon-btn').trigger('click')
    await nextTick()

    const tabs = wrapper.findAll('.day-tab')
    expect(tabs[0].classes()).toContain('active')
    expect(tabs[0].classes()).toContain('today')

    await tabs[2].trigger('click')
    await nextTick()
    await nextTick()
    const updatedTabs = wrapper.findAll('.day-tab')
    expect(updatedTabs[2].classes()).toContain('active')
    expect(updatedTabs[2].classes()).not.toContain('today')
    expect(updatedTabs[0].classes()).not.toContain('active')
    expect(updatedTabs[0].classes()).toContain('today')
    expect(wrapper.text()).toContain('2026-09-23 · 单日课表')
    expect(wrapper.find('.today-link').exists()).toBe(false)
    expect(wrapper.find('.timetable-swipe-panel').classes()).toContain('is-next')
    wrapper.unmount()
  })

  it('日视图中的跨大节连堂只渲染为一张连续课程卡片', async () => {
    mocks.terms.push({
      id: 'term-1', _rev: 1, _updated_at: null, _deleted_at: null,
      name: '2026-2027-1', label: null, start_date: '2026-08-31',
      weeks_total: 20, is_current: 1, archived_at: null,
    })
    mocks.courses.push({
      id: 'course-1', _rev: 1, _updated_at: null, _deleted_at: null,
      term_id: 'term-1', name: '连续课程', short_name: null, teacher: null,
      color: 0, sort_order: 0,
    })
    mocks.slots.push({
      id: 'slot-1', _rev: 1, _updated_at: null, _deleted_at: null,
      course_id: 'course-1', weekday: 1, start_lesson: 1, end_lesson: 4,
      room: 'A101', weeks: '{"ranges":[[1,20]],"only":[],"except":[],"parity":"all"}',
    })
    mocks.periods.push(...[1, 2, 3, 4].map((lesson) => ({
      id: `period-${lesson}`, _rev: 1, _updated_at: null, _deleted_at: null,
      term_id: 'term-1', lesson_no: lesson, start_time: `${8 + lesson}:00`,
      end_time: `${8 + lesson}:50`, big_period: lesson <= 2 ? 1 : 2,
    })))

    const wrapper = mount(TimetableView)
    await flushPromises()
    await wrapper.find('.icon-btn').trigger('click')
    await nextTick()

    expect(wrapper.findAll('.day-period-meta')).toHaveLength(2)
    expect(wrapper.findAll('.day-course')).toHaveLength(1)
    expect(wrapper.find('.day-course-group').attributes('style')).toContain('grid-row: 1 / 3')
    expect(wrapper.find('.day-course').text()).toContain('连续课程')
    expect(wrapper.text()).not.toContain('空闲')
    wrapper.unmount()
  })

  it('周视图将冲突课程聚合，并可转到单日视图查看和编辑', async () => {
    mocks.terms.push({
      id: 'term-1', _rev: 1, _updated_at: null, _deleted_at: null,
      name: '2026-2027-1', label: null, start_date: '2026-08-31',
      weeks_total: 20, is_current: 1, archived_at: null,
    })
    for (const [id, name, color, room] of [
      ['course-1', '课程甲', 0, 'A101'],
      ['course-2', '课程乙', 1, 'B202'],
    ]) {
      mocks.courses.push({
        id, _rev: 1, _updated_at: null, _deleted_at: null,
        term_id: 'term-1', name, short_name: null, teacher: null, color, sort_order: color,
      })
      mocks.slots.push({
        id: `slot-${id}`, _rev: 1, _updated_at: null, _deleted_at: null,
        course_id: id, weekday: 1, start_lesson: 1, end_lesson: 2, room,
        weeks: '{"ranges":[[1,20]],"only":[],"except":[],"parity":"all"}',
      })
    }
    mocks.periods.push(...[1, 2].map((lesson) => ({
      id: `period-${lesson}`, _rev: 1, _updated_at: null, _deleted_at: null,
      term_id: 'term-1', lesson_no: lesson, start_time: `${8 + lesson}:00`,
      end_time: `${8 + lesson}:50`, big_period: 1,
    })))

    const wrapper = mount(TimetableView)
    await flushPromises()

    expect(wrapper.findAll('.week-course-group.has-collision')).toHaveLength(1)
    expect(wrapper.findAll('.week-course')).toHaveLength(2)
    await wrapper.find('.week-collision').trigger('click')
    await nextTick()
    await nextTick()

    expect(mocks.appStore.mobileView).toBe('day')
    expect(wrapper.findAll('.day-course')).toHaveLength(2)
    expect(wrapper.find('.day-course-group').attributes('style')).toContain('grid-template-columns: repeat(2')
    wrapper.unmount()
  })

  it('日视图左右滑动切换相邻日期，周视图左右滑动切换周次', async () => {
    mocks.terms.push({
      id: 'term-1',
      _rev: 1,
      _updated_at: null,
      _deleted_at: null,
      name: '2026-2027-1',
      label: null,
      start_date: '2026-08-31',
      weeks_total: 20,
      is_current: 1,
      archived_at: null,
    })

    const wrapper = mount(TimetableView)
    await flushPromises()
    await wrapper.find('.icon-btn').trigger('click')
    await nextTick()

    const dayGrid = wrapper.find('.day-grid')
    dispatchPointer(dayGrid.element, 'pointerdown', 220, 100)
    dispatchPointer(dayGrid.element, 'pointerup', 150, 106)
    await nextTick()
    expect(wrapper.text()).toContain('2026-09-22 · 单日课表')

    await wrapper.find('.icon-btn').trigger('click')
    await nextTick()
    expect(wrapper.find('.week-label').text()).toBe('第 4 周')
    const weekGrid = wrapper.find('.week-grid')
    dispatchPointer(weekGrid.element, 'pointerdown', 220, 100)
    dispatchPointer(weekGrid.element, 'pointerup', 150, 106)
    await nextTick()
    expect(wrapper.find('.week-label').text()).toBe('第 5 周')
    expect(wrapper.find('.week-head-cell.today').exists()).toBe(false)
    expect(wrapper.find('.week-ctrl .today-link').exists()).toBe(true)
    expect(wrapper.find('.add-course-btn').text()).toBe('+ 添加课程')
    expect(wrapper.find('.timetable-swipe-panel').classes()).toContain('is-next')
    wrapper.unmount()
  })
})

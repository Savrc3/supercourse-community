import { describe, expect, it } from 'vitest'
import { DEFAULT_REMINDER_CONFIG, calculateClassReminderTimes, calculateReminderTimes, dueDate, formatLeadTime, mergeReminderConfig, parseIsoDuration } from './reminder'

const base = {
  id: 'todo-1', kind: 'todo', remind_mode: 'inherit', remind_offsets: null, due_at: '2026-09-05', due_all_day: 1,
  status: '0' as const, _deleted_at: null,
}

describe('reminder calculation', () => {
  it('parses negative ISO durations', () => {
    expect(parseIsoDuration('-P1D')).toBe(-86_400_000)
    expect(parseIsoDuration('-PT2H')).toBe(-7_200_000)
    expect(parseIsoDuration('bad')).toBeNull()
  })

  it('uses 09:00 as all-day due time', () => {
    expect(dueDate(base)?.getHours()).toBe(9)
  })

  it('calculates the single default reminder', () => {
    const now = new Date(2026, 8, 4, 8)
    expect(calculateReminderTimes(base, DEFAULT_REMINDER_CONFIG, now).map((item) => item.offset)).toEqual(['-P1D'])
    expect(calculateReminderTimes({ ...base, remind_mode: 'off' }, DEFAULT_REMINDER_CONFIG, now)).toEqual([])
  })

  it('把偏移渲染成人类可读的提前量', () => {
    expect(formatLeadTime('-P1D')).toBe('1 天')
    expect(formatLeadTime('-PT2H')).toBe('2 小时')
    expect(formatLeadTime('-PT15M')).toBe('15 分钟')
    expect(formatLeadTime('-PT90M')).toBe('90 分钟')
    expect(formatLeadTime('垃圾')).toBe('垃圾')
  })

  it('保留服务端存的 defaults，只认 channels 会覆盖用户设置', () => {
    const merged = mergeReminderConfig({
      defaults: { todo: ['-PT30M'], class: ['-PT5M'] },
      channels: { todo: ['qq'], class: ['qq', 'mobile'] },
    })
    expect(merged.defaults.todo).toEqual(['-PT30M'])
    expect(merged.defaults.class).toEqual(['-PT5M'])
    expect(merged.channels.class).toEqual(['qq', 'mobile'])

    // 非法值/缺失时回退默认，不能把配置清空
    const fallback = mergeReminderConfig({ defaults: { todo: ['不是时长'], class: 'x' } })
    expect(fallback.defaults.todo).toEqual(DEFAULT_REMINDER_CONFIG.defaults.todo)
    expect(fallback.defaults.class).toEqual(DEFAULT_REMINDER_CONFIG.defaults.class)

    const empty = mergeReminderConfig({})
    expect(empty.defaults).toEqual(DEFAULT_REMINDER_CONFIG.defaults)
    expect(empty.channels).toEqual(DEFAULT_REMINDER_CONFIG.channels)
  })

  it('calculates the next class reminder 15 minutes before class', () => {
    const result = calculateClassReminderTimes(
      [{ id: 't', _rev: 1, _updated_at: null, _deleted_at: null, name: '2026-1', label: null, start_date: '2026-08-31', weeks_total: 20, is_current: 1, archived_at: null }],
      [{ id: 'c', _rev: 1, _updated_at: null, _deleted_at: null, term_id: 't', name: '模拟电子技术', short_name: null, teacher: null, code: null, color: 0, credit: null, exam_at: null, exam_room: null, exam_note: null, textbook: null, grade_breakdown: null, note: null, sort_order: 0 }],
      [{ id: 's', _rev: 1, _updated_at: null, _deleted_at: null, course_id: 'c', weekday: 1, start_lesson: 1, end_lesson: 1, room: '实验楼', weeks: '{"ranges":[[1,16]],"only":[],"except":[],"parity":"all"}' }],
      [{ id: 'p', _rev: 1, _updated_at: null, _deleted_at: null, term_id: 't', lesson_no: 1, start_time: '08:00', end_time: '08:50', big_period: 1 }],
      DEFAULT_REMINDER_CONFIG,
      new Date(2026, 8, 4, 8),
    )
    expect(result[0]?.fireAt).toEqual(new Date(2026, 8, 7, 7, 45))
  })

  it('学期开始前不排课提醒（currentWeek 钳制不能用来越界判断）', () => {
    const term = { id: 't', _rev: 1, _updated_at: null, _deleted_at: null, name: '2026-1', label: null, start_date: '2026-09-07', weeks_total: 2, is_current: 1, archived_at: null }
    const course = { id: 'c', _rev: 1, _updated_at: null, _deleted_at: null, term_id: 't', name: '模拟电子技术', short_name: null, teacher: null, code: null, color: 0, credit: null, exam_at: null, exam_room: null, exam_note: null, textbook: null, grade_breakdown: null, note: null, sort_order: 0 }
    // 周四的课；2026-09-03 是开学前的周四，2026-09-24 是结课后的周四
    const slot = { id: 's', _rev: 1, _updated_at: null, _deleted_at: null, course_id: 'c', weekday: 4, start_lesson: 1, end_lesson: 1, room: '实验楼', weeks: '{}' }
    const periods = [{ id: 'p', _rev: 1, _updated_at: null, _deleted_at: null, term_id: 't', lesson_no: 1, start_time: '08:00', end_time: '08:50', big_period: 1 }]

    const before = calculateClassReminderTimes([term], [course], [slot], periods, DEFAULT_REMINDER_CONFIG, new Date(2026, 8, 3, 6))
    // 09-03 是开学前的周四，不该排；学期内的 09-10、09-17 照常
    expect(before.map((item) => item.startsAt.getDate())).toEqual([10, 17])

    const inside = calculateClassReminderTimes([term], [course], [slot], periods, DEFAULT_REMINDER_CONFIG, new Date(2026, 8, 8, 6))
    expect(inside.map((item) => item.startsAt.getDate())).toEqual([10, 17])

    const after = calculateClassReminderTimes([term], [course], [slot], periods, DEFAULT_REMINDER_CONFIG, new Date(2026, 8, 21, 6))
    expect(after).toEqual([])
  })
})

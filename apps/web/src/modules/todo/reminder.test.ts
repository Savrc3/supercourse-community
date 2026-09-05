import { describe, expect, it } from 'vitest'
import { DEFAULT_REMINDER_CONFIG, calculateClassReminderTimes, calculateReminderTimes, dueDate, encodeOffsets, parseIsoDuration } from './reminder'

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

  it('normalizes custom offset input', () => {
    expect(encodeOffsets('-P1D, -P1D, -PT2H, invalid')).toBe('["-P1D","-PT2H"]')
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
})

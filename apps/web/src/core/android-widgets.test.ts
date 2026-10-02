import { describe, expect, it } from 'vitest'

import type { CourseRow, CourseSlotRow, LessonPeriodRow, TermRow, TimetableOverrideRow, TodoRow } from '../db/db'
import { androidWidgetMood, buildAndroidWidgetSnapshot } from './android-widgets'

const sym = { _rev: 1, _updated_at: null, _deleted_at: null }

describe('Android widget snapshot', () => {
  it('derives real course events with one-off changes and keeps overdue todos first', () => {
    const term = { ...sym, id: 'term', name: '秋季', label: null, start_date: '2026-09-07', weeks_total: 2, is_current: 1, archived_at: null } as TermRow
    const courses = [
      { ...sym, id: 'c1', term_id: 'term', name: '高等数学', short_name: null, teacher: null, code: null, color: 0, credit: null, exam_at: null, exam_room: null, exam_note: null, textbook: null, grade_breakdown: null, note: null, sort_order: 0 },
      { ...sym, id: 'c2', term_id: 'term', name: '物理', short_name: null, teacher: null, code: null, color: 1, credit: null, exam_at: null, exam_room: null, exam_note: null, textbook: null, grade_breakdown: null, note: null, sort_order: 1 },
    ] as CourseRow[]
    const slots = [
      { ...sym, id: 's1', course_id: 'c1', weekday: 1, start_lesson: 1, end_lesson: 2, room: 'A101', weeks: '{"ranges":[[1,2]],"only":[],"except":[],"parity":"all"}' },
      { ...sym, id: 's2', course_id: 'c2', weekday: 2, start_lesson: 1, end_lesson: 1, room: 'B201', weeks: '{"ranges":[[1,2]],"only":[],"except":[],"parity":"all"}' },
    ] as CourseSlotRow[]
    const periods = [
      { ...sym, id: 'p1', term_id: 'term', lesson_no: 1, start_time: '08:00', end_time: '08:45', big_period: 1 },
      { ...sym, id: 'p2', term_id: 'term', lesson_no: 2, start_time: '08:55', end_time: '09:40', big_period: 1 },
    ] as LessonPeriodRow[]
    const overrides = [{ ...sym, id: 'o1', term_id: 'term', day: '2026-09-08', action: 'move', course_id: 'c2', slot_id: 's2', to_weekday: 1, to_start_lesson: 2, to_end_lesson: 2, room: 'C303', note: null }] as TimetableOverrideRow[]
    const todos = [
      { ...sym, id: 'late', title: '逾期任务', course_id: null, kind: 'task', body: 'private', body_text: 'private', due_at: '2026-09-07T09:00', start_at: null, due_all_day: 0, repeat: null, status: '0', done_at: null, priority: 0, tags: '', remind_mode: 'inherit', remind_offsets: null, sort_order: 0, created_at: '2026-09-01' },
      { ...sym, id: 'later', title: '稍后任务', course_id: 'c1', kind: 'task', body: 'private', body_text: 'private', due_at: '2026-09-09T10:00', start_at: null, due_all_day: 0, repeat: null, status: '0', done_at: null, priority: 0, tags: '', remind_mode: 'inherit', remind_offsets: null, sort_order: 0, created_at: '2026-09-02' },
    ] as TodoRow[]
    const snapshot = buildAndroidWidgetSnapshot({ terms: [term], courses, slots, periods, overrides, todos, now: new Date('2026-09-07T07:00:00') })
    expect(snapshot.initialized).toBe(true)
    expect(snapshot.events).toContainEqual(expect.objectContaining({ date: '2026-09-07', title: '高等数学', start: '08:00', end: '09:40', room: 'A101' }))
    expect(snapshot.events).toContainEqual(expect.objectContaining({ date: '2026-09-07', title: '物理', start: '08:55', end: '09:40', room: 'C303' }))
    expect(snapshot.events.some((event) => event.date === '2026-09-08' && event.title === '物理')).toBe(false)
    expect(snapshot.todos.map((todo) => todo.id)).toEqual(['late', 'later'])
    expect(JSON.stringify(snapshot)).not.toContain('private')
    expect(androidWidgetMood(snapshot, new Date('2026-09-07T07:00:00'))).toBe('class')
    expect(androidWidgetMood(snapshot, new Date('2026-09-07T10:00:00'))).toBe('urgent')
    expect(androidWidgetMood({ ...snapshot, todos: [] }, new Date('2026-09-07T10:00:00'))).toBe('done')
    const busySnapshot = {
      ...snapshot,
      events: [...snapshot.events, ...[1, 2, 3].map((index) => ({
        ...snapshot.events[0]!, id: `busy-${index}`, start: `1${index}:00`, end: `1${index}:45`,
      }))],
    }
    expect(androidWidgetMood(busySnapshot, new Date('2026-09-07T07:00:00'))).toBe('busy')
  })

  it('does not infer idle data when there is no current term', () => {
    const snapshot = buildAndroidWidgetSnapshot({ terms: [], courses: [], slots: [], periods: [], overrides: [], todos: [] })
    expect(snapshot.initialized).toBe(false)
    expect(snapshot.events).toEqual([])
    expect(androidWidgetMood(snapshot)).toBe('unavailable')
  })
})

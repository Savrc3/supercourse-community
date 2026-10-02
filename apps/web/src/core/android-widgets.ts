import { liveQuery } from 'dexie'

import { db, type CourseRow, type CourseSlotRow, type LessonPeriodRow, type TermRow, type TimetableOverrideRow, type TodoRow } from '../db/db'
import { canonicalCourseIds } from './courses'
import { WIDGET_COPY } from './android-widget-copy'
import { applyDayOverrides, canonicalTermStartDate, isDateInTerm, mergeConsecutive, shiftISODate, weekDates, type CourseSlot, type DayOverride, type LessonPeriod, type Term } from '../modules/timetable/derive'
import { isDoneStatus, sortTodos } from '../modules/todo/derive'

export interface WidgetCourseEvent {
  id: string
  courseId: string
  title: string
  room: string | null
  date: string
  start: string
  end: string
}

export interface WidgetTodo {
  id: string
  title: string
  dueAt: string | null
  allDay: boolean
  courseName: string | null
}

export interface AndroidWidgetSnapshot {
  initialized: boolean
  hasCurrentTerm: boolean
  updatedAt: string
  termName: string | null
  events: WidgetCourseEvent[]
  todos: WidgetTodo[]
  copy: typeof WIDGET_COPY
}

/** Convert current local database data into the small, private payload consumed by Android widgets. */
export function buildAndroidWidgetSnapshot(input: {
  terms: TermRow[]
  courses: CourseRow[]
  slots: CourseSlotRow[]
  overrides: TimetableOverrideRow[]
  periods: LessonPeriodRow[]
  todos: TodoRow[]
  now?: Date
  dataReady?: boolean
}): AndroidWidgetSnapshot {
  const now = input.now ?? new Date()
  const termRow = input.terms.find((term) => term.is_current === 1 && !term._deleted_at && !term.archived_at)
  const term = termRow ? ({ ...termRow, start_date: canonicalTermStartDate(termRow) } as Term) : null
  const coursePool = input.courses.filter((course) => !course._deleted_at && term && course.term_id === term.id)
  const canonicalIds = canonicalCourseIds(coursePool)
  const liveCourses = coursePool.filter((course) => canonicalIds.get(course.id) === course.id)
  const courseMap = new Map(liveCourses.map((course) => [course.id, course]))
  const slots = input.slots.filter((slot) => !slot._deleted_at && courseMap.has(slot.course_id)) as CourseSlot[]
  const periods = input.periods.filter((period) => !period._deleted_at && (!term || period.term_id === term.id)) as LessonPeriod[]
  const overrides = input.overrides.filter((item) => !item._deleted_at && (!term || item.term_id === term.id)).map((item) => ({
    day: item.day, action: item.action, slotId: item.slot_id, courseId: item.course_id,
    room: item.room, toWeekday: item.to_weekday, toStartLesson: item.to_start_lesson, toEndLesson: item.to_end_lesson,
  })) as DayOverride[]
  const events: WidgetCourseEvent[] = []

  if (term && periods.length) {
    for (let week = 1; week <= term.weeks_total; week += 1) {
      const { monday } = weekDates(term.start_date, week)
      const dates = Array.from({ length: 7 }, (_, day) => ({ weekday: day + 1, date: shiftISODate(monday, day) }))
      const merged = mergeConsecutive(slots, week)
      const dayBlocks = applyDayOverrides(merged, dates, overrides)
      for (const block of dayBlocks) {
        const date = dates.find((item) => item.weekday === block.weekday)?.date
        if (!date || !isDateInTerm(term.start_date, term.weeks_total, date)) continue
        const startPeriod = periods.find((period) => period.lesson_no === block.startLesson)
        const endPeriod = periods.find((period) => period.lesson_no === block.endLesson)
        const course = courseMap.get(block.courseId)
        if (!startPeriod || !endPeriod || !course) continue
        events.push({
          id: `${date}:${block.slotId}:${block.startLesson}:${block.endLesson}`,
          courseId: course.id,
          title: course.name,
          room: block.room,
          date,
          start: startPeriod.start_time,
          end: endPeriod.end_time,
        })
      }
    }
  }
  events.sort((a, b) => a.date.localeCompare(b.date) || a.start.localeCompare(b.start) || a.end.localeCompare(b.end) || a.id.localeCompare(b.id))

  const liveTodos = sortTodos(input.todos.filter((todo) => !todo._deleted_at && !isDoneStatus(todo.status)))
  const todos = liveTodos.map((todo) => ({
    id: todo.id,
    title: todo.title,
    dueAt: todo.due_at,
    allDay: todo.due_all_day === 1,
    courseName: todo.course_id ? courseMap.get(todo.course_id)?.name ?? null : null,
  }))
  return {
    initialized: Boolean(input.dataReady || term),
    hasCurrentTerm: Boolean(term),
    updatedAt: now.toISOString(),
    termName: term?.name ?? null,
    events,
    todos,
    copy: WIDGET_COPY,
  }
}

export type WidgetMood = 'unavailable' | 'busy' | 'class' | 'urgent' | 'done' | 'free'

/** Derive one factual copy state for the current local day. */
export function androidWidgetMood(snapshot: AndroidWidgetSnapshot, now = new Date(), kind: 'guide' | 'today' | 'overview' | 'todos' = 'guide'): WidgetMood {
  if (!snapshot.initialized) return 'unavailable'
  if (!snapshot.hasCurrentTerm && kind !== 'todos') return 'unavailable'
  const today = localISO(now)
  const todaysEvents = snapshot.events.filter((event) => event.date === today)
  const remaining = todaysEvents.filter((event) => event.end > localTime(now))
  if (kind === 'todos') {
    if (snapshot.todos.length === 0) return 'free'
    const hasDeadlineTodayOrOverdue = snapshot.todos.some((todo) => todo.dueAt !== null && todo.dueAt.slice(0, 10) <= today)
    return hasDeadlineTodayOrOverdue ? 'urgent' : 'class'
  }
  if (remaining.length >= 4) return 'busy'
  if (remaining.length) return 'class'
  const hasDeadlineTodayOrOverdue = snapshot.todos.some((todo) =>
    todo.dueAt !== null && todo.dueAt.slice(0, 10) <= today,
  )
  if (hasDeadlineTodayOrOverdue) return 'urgent'
  return todaysEvents.length > 0 ? 'done' : 'free'
}

/** Start Dexie live-query mirroring; catches direct writes from import, restore, sync, and ordinary CRUD. */
export interface AndroidWidgetMirror {
  refresh(): Promise<void>
  stop(): void
}

export function startAndroidWidgetMirror(
  onSnapshot: (snapshot: AndroidWidgetSnapshot) => Promise<void> | void,
  isDataReady: () => boolean = () => false,
): AndroidWidgetMirror {
  let timer: ReturnType<typeof setTimeout> | undefined
  const loadSnapshot = async () => {
    const [terms, courses, slots, overrides, periods, todos] = await Promise.all([
      db.term.toArray(), db.course.toArray(), db.course_slot.toArray(), db.timetable_override.toArray(), db.lesson_period.toArray(), db.todo.toArray(),
    ])
    return buildAndroidWidgetSnapshot({ terms, courses, slots, overrides, periods, todos, dataReady: isDataReady() })
  }
  const sendSnapshot = async (snapshot: AndroidWidgetSnapshot) => {
    try {
      await onSnapshot(snapshot)
    } catch (error) {
      console.warn('Android widget snapshot update failed', error)
    }
  }
  const subscription = liveQuery(loadSnapshot).subscribe({
    next: (snapshot) => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => void sendSnapshot(snapshot), 100)
    },
    error: (error) => console.warn('Android widget database watch failed', error),
  })
  return {
    refresh: async () => { await sendSnapshot(await loadSnapshot()) },
    stop: () => { if (timer) clearTimeout(timer); subscription.unsubscribe() },
  }
}

function localISO(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function localTime(date: Date): string {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

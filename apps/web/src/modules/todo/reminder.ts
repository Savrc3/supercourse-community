import type { CourseRow, CourseSlotRow, LessonPeriodRow, TermRow, TodoRow } from '../../db/db'
import { currentWeek, inTermRange, parseWeeks, slotInWeek } from '../timetable/derive'

export type ReminderChannel = 'qq' | 'mobile' | 'windows'
export type ReminderKind = 'todo' | 'class'

export interface ReminderConfig {
  defaults: Record<ReminderKind, string[]>
  channels: Record<ReminderKind, ReminderChannel[]>
}

export interface ReminderTime {
  todoId: string
  offset: string
  fireAt: Date
}

export interface ClassReminderTime {
  id: string
  courseId: string
  courseName: string
  room: string | null
  startsAt: Date
  fireAt: Date
}

export const DEFAULT_REMINDER_CONFIG: ReminderConfig = {
  defaults: { todo: ['-P1D'], class: ['-PT15M'] },
  channels: {
    todo: ['qq', 'mobile', 'windows'],
    class: ['qq', 'mobile', 'windows'],
  },
}

export function parseIsoDuration(raw: string): number | null {
  const match = /^(-)?P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$/i.exec(raw.trim())
  if (!match || !match.slice(2).some(Boolean)) return null
  const milliseconds = ((Number(match[2] ?? 0) * 24 + Number(match[3] ?? 0)) * 60 + Number(match[4] ?? 0)) * 60 * 1000
  return match[1] ? -milliseconds : milliseconds
}

export function dueDate(todo: Pick<TodoRow, 'due_at' | 'due_all_day'>): Date | null {
  if (!todo.due_at) return null
  const date = todo.due_at.slice(0, 10).split('-').map(Number)
  if (date.length !== 3 || date.some((part) => !Number.isFinite(part))) return null
  if (todo.due_all_day === 1 || !todo.due_at.includes('T')) return new Date(date[0], date[1] - 1, date[2], 9, 0, 0, 0)
  const parsed = new Date(todo.due_at)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function reminderOffsets(todo: Pick<TodoRow, 'remind_mode'>, config: ReminderConfig): string[] {
  return todo.remind_mode === 'off' ? [] : config.defaults.todo
}

export function calculateReminderTimes(
  todo: Pick<TodoRow, 'id' | 'remind_mode' | 'due_at' | 'due_all_day' | 'status' | '_deleted_at'>,
  config: ReminderConfig = DEFAULT_REMINDER_CONFIG,
  now = new Date(),
): ReminderTime[] {
  if (todo._deleted_at || todo.status !== '0') return []
  const due = dueDate(todo)
  if (!due) return []
  return reminderOffsets(todo, config)
    .map((offset) => ({ offset, fireAt: new Date(due.getTime() + (parseIsoDuration(offset) ?? 0)), todoId: todo.id }))
    .filter((item) => item.fireAt.getTime() >= now.getTime() - 120_000)
    .sort((a, b) => a.fireAt.getTime() - b.fireAt.getTime())
}

function dayWithTime(day: Date, text: string): Date | null {
  const [hours, minutes] = text.split(':').map(Number)
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return null
  return new Date(day.getFullYear(), day.getMonth(), day.getDate(), hours, minutes, 0, 0)
}

export function calculateClassReminderTimes(
  terms: TermRow[],
  courses: CourseRow[],
  slots: CourseSlotRow[],
  periods: LessonPeriodRow[],
  config: ReminderConfig = DEFAULT_REMINDER_CONFIG,
  now = new Date(),
): ClassReminderTime[] {
  const term = terms
    .filter((item) => !item._deleted_at && !item.archived_at)
    .sort((a, b) => Number(b.is_current) - Number(a.is_current))[0]
  const offset = parseIsoDuration(config.defaults.class[0] ?? '-PT15M')
  if (!term || offset === null) return []
  const coursesById = new Map(courses.filter((item) => !item._deleted_at && item.term_id === term.id).map((item) => [item.id, item]))
  const periodsByNo = new Map(periods.filter((item) => !item._deleted_at && item.term_id === term.id).map((item) => [item.lesson_no, item]))
  const result: ClassReminderTime[] = []
  for (let dayIndex = 0; dayIndex < 56; dayIndex += 1) {
    const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + dayIndex)
    const dayIso = isoDate(day)
    // 学期区间外的日期直接跳过：currentWeek 会钳制，不能用它判断是否在学期内。
    if (!inTermRange(term.start_date, dayIso, term.weeks_total)) continue
    const week = currentWeek(term.start_date, dayIso, term.weeks_total)
    for (const slot of slots) {
      const weekday = day.getDay() === 0 ? 7 : day.getDay()
      if (slot._deleted_at || slot.weekday !== weekday) continue
      const course = coursesById.get(slot.course_id)
      const startPeriod = periodsByNo.get(slot.start_lesson)
      if (!course || !startPeriod || !slotInWeek(parseWeeks(slot.weeks), week)) continue
      const startsAt = dayWithTime(day, startPeriod.start_time)
      if (!startsAt) continue
      const fireAt = new Date(startsAt.getTime() + offset)
      if (fireAt.getTime() < now.getTime() - 120_000) continue
      result.push({ id: `${slot.id}:${isoDate(day)}`, courseId: course.id, courseName: course.name, room: slot.room, startsAt, fireAt })
    }
  }
  return result.sort((a, b) => a.fireAt.getTime() - b.fireAt.getTime()).slice(0, 64)
}

function isoDate(value: Date): string {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

/** 把提前量（毫秒）渲染成人类可读文本。 */
export function formatLeadDuration(ms: number): string {
  const seconds = Math.max(Math.round(Math.abs(ms) / 1000), 1)
  if (seconds % 86400 === 0 && seconds >= 86400) return `${seconds / 86400} 天`
  if (seconds % 3600 === 0 && seconds >= 3600) return `${seconds / 3600} 小时`
  return `${Math.max(Math.round(seconds / 60), 1)} 分钟`
}

/** 把 ISO 时长偏移转成人类可读的提前量（"-P1D" → "1 天"，"-PT15M" → "15 分钟"）。 */
export function formatLeadTime(offset: string): string {
  const ms = parseIsoDuration(offset)
  return ms === null ? offset : formatLeadDuration(ms)
}

function normalizeOffsets(value: unknown, fallback: string[]): string[] {
  if (!Array.isArray(value)) return [...fallback]
  const offsets = value.filter((item): item is string => typeof item === 'string' && parseIsoDuration(item) !== null)
  return offsets.length > 0 ? offsets : [...fallback]
}

export function mergeReminderConfig(value: unknown): ReminderConfig {
  const stored = (value && typeof value === 'object' ? value : {}) as {
    channels?: Record<string, ReminderChannel[]>
    defaults?: Record<string, string[]>
  }
  const legacy = stored.channels ?? {}
  const todoChannels = Array.isArray(legacy.todo) ? legacy.todo : DEFAULT_REMINDER_CONFIG.channels.todo
  const classChannels = Array.isArray(legacy.class) ? legacy.class : todoChannels
  // 服务端存的是用户改过的提醒设置，defaults 必须保留——只认 channels 会让
  // 用户自定义的提前量在每次重载后被默认值覆盖。
  return {
    defaults: {
      todo: normalizeOffsets(stored.defaults?.todo, DEFAULT_REMINDER_CONFIG.defaults.todo),
      class: normalizeOffsets(stored.defaults?.class, DEFAULT_REMINDER_CONFIG.defaults.class),
    },
    channels: { todo: todoChannels, class: classChannels },
  }
}

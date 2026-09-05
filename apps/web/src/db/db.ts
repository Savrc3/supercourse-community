/** IndexedDB 镜像：三端各自离线优先的真相副本。 */

import Dexie, { type Table } from 'dexie'

export interface SymRow {
  id: string
  _rev: number
  _updated_at: string | null
  _deleted_at: string | null
}

export interface TermRow extends SymRow {
  name: string
  label: string | null
  start_date: string
  weeks_total: number
  is_current: number
  archived_at: string | null
}

export interface CourseRow extends SymRow {
  term_id: string
  name: string
  short_name: string | null
  teacher: string | null
  code: string | null
  color: number
  credit: number | null
  exam_at: string | null
  exam_room: string | null
  exam_note: string | null
  textbook: string | null
  grade_breakdown: string | null
  note: string | null
  sort_order: number
}

export interface CourseSlotRow extends SymRow {
  course_id: string
  weekday: number
  start_lesson: number
  end_lesson: number
  room: string | null
  weeks: string
}

export interface TimetableOverrideRow extends SymRow {
  term_id: string
  day: string
  action: 'room' | 'cancel' | 'move' | string
  course_id: string | null
  slot_id: string | null
  to_weekday: number | null
  to_start_lesson: number | null
  to_end_lesson: number | null
  room: string | null
  note: string | null
}

export type TodoStatus = '0' | '1'
export type TodoPriority = 0 | 1 | 2

export interface TodoRow extends SymRow {
  course_id: string | null
  kind: string
  title: string
  body: string
  body_text: string
  due_at: string | null
  start_at: string | null
  due_all_day: number
  repeat: string | null
  status: TodoStatus
  done_at: string | null
  priority: TodoPriority
  tags: string
  remind_mode: string
  remind_offsets: string | null
  sort_order: number
  created_at: string
}

export interface SettingRow extends SymRow {
  key: string
  value: string
}

export interface MediaRow extends SymRow {
  sha256: string
  mime: string
  ext: string
  bytes: number
  width: number | null
  height: number | null
  filename: string | null
  uploaded: number
  created_at: string
  blob?: Blob
}

export interface AttachmentRow extends SymRow {
  media_id: string
  owner_type: string
  owner_id: string
  position: number
  caption: string | null
}

export interface LessonPeriodRow extends SymRow {
  term_id: string
  lesson_no: number
  start_time: string
  end_time: string
  big_period: number
}

export interface OutboxRow {
  op_id: string
  entity: string
  id: string
  set: Record<string, unknown>
  base_rev: number
  deleted?: boolean
  created_at: string
}

export class SupercourseDB extends Dexie {
  term!: Table<TermRow, string>
  course!: Table<CourseRow, string>
  course_slot!: Table<CourseSlotRow, string>
  timetable_override!: Table<TimetableOverrideRow, string>
  lesson_period!: Table<LessonPeriodRow, string>
  todo!: Table<TodoRow, string>
  setting!: Table<SettingRow, string>
  media!: Table<MediaRow, string>
  attachment!: Table<AttachmentRow, string>
  outbox!: Table<OutboxRow, string>
  meta!: Table<{ key: string; value: string }, string>

  constructor() {
    super('supercourse')
    this.version(1).stores({
      // 主键 + 索引；同步专用前缀字段用 _ 避免与业务字段冲突。
      term: 'id, _rev, name',
      course: 'id, _rev, term_id, name',
      course_slot: 'id, _rev, course_id, weekday',
      lesson_period: 'id, _rev, term_id, lesson_no',
      todo: 'id, _rev, course_id, status, due_at',
      setting: 'id, _rev, key',
      outbox: 'op_id, created_at',
      meta: 'key',
    })
    this.version(2).stores({
      timetable_override: 'id, _rev, term_id, day, course_id, slot_id',
    })
    this.version(3).stores({
      media: 'id, _rev, sha256, uploaded, created_at',
      attachment: 'id, _rev, media_id, owner_type, owner_id, position',
    })
  }
}

export const db = new SupercourseDB()

export const ENTITIES = [
  'term',
  'course',
  'course_slot',
  'timetable_override',
  'lesson_period',
  'todo',
  'media',
  'attachment',
  'setting',
] as const

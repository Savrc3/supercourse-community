/** 课表推导层：纯函数，无副作用。 */

export interface LessonPeriod {
  id: string
  lesson_no: number
  start_time: string
  end_time: string
  big_period: number
}

export interface Term {
  id: string
  name: string
  label: string | null
  start_date: string
  weeks_total: number
  is_current: number
  archived_at: string | null
}

export interface Course {
  id: string
  term_id: string
  name: string
  short_name: string | null
  teacher: string | null
  color: number
  sort_order: number
}

export interface CourseSlot {
  id: string
  course_id: string
  weekday: number
  start_lesson: number
  end_lesson: number
  room: string | null
  weeks: string
}

export interface WeeksSpec {
  ranges: number[][]
  only: number[]
  except: number[]
  parity: 'all' | 'odd' | 'even'
}

/** 从 JSON 字符串解析周次规则（容错：非法返回空规则）。 */
export function parseWeeks(raw: string): WeeksSpec {
  try {
    const obj = JSON.parse(raw) as WeeksSpec
    return {
      ranges: Array.isArray(obj.ranges) ? obj.ranges : [],
      only: Array.isArray(obj.only) ? obj.only : [],
      except: Array.isArray(obj.except) ? obj.except : [],
      parity: obj.parity ?? 'all',
    }
  } catch {
    return { ranges: [], only: [], except: [], parity: 'all' }
  }
}

/** 某课程格是否在指定周次显示（单双周过滤 + except 剔除）。 */
export function slotInWeek(weeks: WeeksSpec, week: number): boolean {
  if (weeks.parity === 'odd' && week % 2 === 0) return false
  if (weeks.parity === 'even' && week % 2 === 1) return false
  const inRange = weeks.ranges.some(([a, b]) => week >= a && week <= b)
  const inOnly = weeks.only.includes(week)
  const inExcept = weeks.except.includes(week)
  if (inExcept) return false
  if (inOnly) return true
  if (weeks.ranges.length === 0 && weeks.only.length === 0) return true
  return inRange
}

/** 由 term.start_date 推算某一周的日期范围。 */
export function weekDates(termStart: string, week: number): { monday: string; sunday: string } {
  const base = parseISO(termStart)
  const monday = addDays(base, (week - 1) * 7)
  const sunday = addDays(base, (week - 1) * 7 + 6)
  return { monday: toISO(monday), sunday: toISO(sunday) }
}

/** 当前第几周（从 term.start_date 算起，早于/晚于都钳制到 1..weeks_total）。 */
export function currentWeek(termStart: string, today: string, weeksTotal: number): number {
  const base = parseISO(termStart)
  const now = parseISO(today)
  const diffDays = Math.floor((now.getTime() - base.getTime()) / 86400000)
  const week = Math.floor(diffDays / 7) + 1
  return Math.max(1, Math.min(week, weeksTotal))
}

/** 修复旧版演示学期的错误起始日；其它用户学期保持原值。 */
export function canonicalTermStartDate(term: Pick<Term, 'name' | 'start_date'>): string {
  return term.name === '2026-2027-1' && term.start_date === '2026-09-07'
    ? '2026-08-31'
    : term.start_date
}

/** 星期标签头：给定周次内的 7 天（含日期）。 */
export function weekHeader(termStart: string, week: number): { weekday: number; label: string; date: string }[] {
  const { monday } = weekDates(termStart, week)
  const base = parseISO(monday)
  const names = ['一', '二', '三', '四', '五', '六', '日']
  return names.map((name, i) => {
    const d = addDays(base, i)
    return {
      weekday: i + 1,
      label: name,
      date: toISO(d),
    }
  })
}

/** 小节号 → 时间段（未找到返回 null）。 */
export function lessonTime(periods: LessonPeriod[], lessonNo: number): { start: string; end: string } | null {
  const p = periods.find((x) => x.lesson_no === lessonNo)
  return p ? { start: p.start_time, end: p.end_time } : null
}

/** 连堂合并：同 course 且小节连续（start_lesson..end_lesson 覆盖）聚为一个长方格。 */
export interface MergedBlock {
  slotId: string
  courseId: string
  weekday: number
  startLesson: number
  endLesson: number
  room: string | null
  weeks: WeeksSpec
}

export interface DayOverride {
  day: string
  action: 'room' | 'cancel' | 'move' | string
  slotId?: string | null
  courseId?: string | null
  room?: string | null
  toWeekday?: number | null
  toStartLesson?: number | null
  toEndLesson?: number | null
}

/** 将指定周内的具体日期覆盖应用到显示块，固定课表数据保持不变。 */
export function applyDayOverrides(
  blocks: MergedBlock[],
  dates: { weekday: number; date: string }[],
  overrides: DayOverride[],
): MergedBlock[] {
  const result: MergedBlock[] = []
  for (const block of blocks) {
    const date = dates.find((item) => item.weekday === block.weekday)?.date
    const override = date
      ? overrides.find(
        (item) =>
          item.day === date &&
          (item.slotId === block.slotId || item.courseId === block.courseId),
      )
      : undefined
    if (!override) {
      result.push(block)
    } else if (override.action === 'cancel') {
      continue
    } else if (override.action === 'move') {
      result.push({
        ...block,
        weekday: override.toWeekday ?? block.weekday,
        startLesson: override.toStartLesson ?? block.startLesson,
        endLesson: override.toEndLesson ?? block.endLesson,
        room: override.room ?? block.room,
      })
    } else {
      result.push({ ...block, room: override.room ?? block.room })
    }
  }
  return result
}

export function mergeConsecutive(
  slots: CourseSlot[],
  week: number,
): MergedBlock[] {
  // 先过滤本显示、非删除格，按 weekday / start_lesson 排序
  const seen = new Set<string>()
  const visible = slots
    .filter((s) => slotInWeek(parseWeeks(s.weeks), week))
    .filter((s) => {
      const key = JSON.stringify([
        s.course_id,
        s.weekday,
        s.start_lesson,
        s.end_lesson,
        s.room,
        parseWeeks(s.weeks),
      ])
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    .sort((a, b) => a.weekday - b.weekday || a.start_lesson - b.start_lesson)
  const merged: MergedBlock[] = []
  for (const slot of visible) {
    const last = merged[merged.length - 1]
    if (
      last &&
      last.weekday === slot.weekday &&
      last.courseId === slot.course_id &&
      slot.start_lesson === last.endLesson + 1
    ) {
      // 延伸到当前格
      last.endLesson = Math.max(last.endLesson, slot.end_lesson)
    } else {
      merged.push({
        slotId: slot.id,
        courseId: slot.course_id,
        weekday: slot.weekday,
        startLesson: slot.start_lesson,
        endLesson: slot.end_lesson,
        room: slot.room,
        weeks: parseWeeks(slot.weeks),
      })
    }
  }
  return merged
}

/** 长课程名缩写：超过 maxLen 截断并加省略号。 */
export function truncateName(name: string, maxLen = 6): string {
  if (name.length <= maxLen) return name
  return `${name.slice(0, maxLen)}…`
}

/** 大节分隔线：由相邻小节的结束时间与下一节开始时间间隙推导（>0 分钟即分隔）。 */
export interface BigPeriodLine {
  afterLesson: number
  gapMinutes: number
}

export function bigPeriodLines(
  periods: LessonPeriod[],
): BigPeriodLine[] {
  const sorted = [...periods].sort((a, b) => a.lesson_no - b.lesson_no)
  const lines: BigPeriodLine[] = []
  for (let i = 0; i < sorted.length; i++) {
    const cur = sorted[i]
    const next = sorted[i + 1]
    if (!next) continue
    const gap = minutesBetween(cur.end_time, next.start_time)
    if (gap > 0) {
      lines.push({ afterLesson: cur.lesson_no, gapMinutes: gap })
    }
  }
  return lines
}

/** 大节行：由作息表按 big_period 聚合，供周视图网格做行锚点（不写死大节数）。 */
export interface BigPeriodRow {
  big: number
  start: string
  end: string
  lessons: number[]
  firstLesson: number
  lastLesson: number
}

export function deriveBigPeriodRows(
  periods: LessonPeriod[],
): BigPeriodRow[] {
  const byBig = new Map<number, LessonPeriod[]>()
  for (const p of periods) {
    const arr = byBig.get(p.big_period) ?? []
    arr.push(p)
    byBig.set(p.big_period, arr)
  }
  const rows: BigPeriodRow[] = []
  for (const big of Array.from(byBig.keys()).sort((a, b) => a - b)) {
    const ps = byBig.get(big)!.sort((a, b) => a.lesson_no - b.lesson_no)
    rows.push({
      big,
      start: ps[0].start_time,
      end: ps[ps.length - 1].end_time,
      lessons: ps.map((p) => p.lesson_no),
      firstLesson: ps[0].lesson_no,
      lastLesson: ps[ps.length - 1].lesson_no,
    })
  }
  return rows
}

/** 把连堂课块（startLesson..endLesson）映射到它跨越的大节行索引区间。 */
export function blockRowSpan(
  block: MergedBlock,
  rows: BigPeriodRow[],
): { from: number; to: number } {
  const from = rows.findIndex(
    (r) => block.startLesson >= r.firstLesson && block.startLesson <= r.lastLesson,
  )
  const to = rows.findIndex(
    (r) => block.endLesson >= r.firstLesson && block.endLesson <= r.lastLesson,
  )
  return { from: from === -1 ? 0 : from, to: to === -1 ? from : to }
}

/** 今日视图单帧条目：一块课 + 起止时间 + 相对当前时刻的状态。 */
export interface TodayTimelineItem {
  slotId: string
  courseId: string
  room: string | null
  start: string
  end: string
  startMin: number
  endMin: number
  status: 'done' | 'ongoing' | 'upcoming'
}

export interface TodayTimeline {
  items: TodayTimelineItem[]
  nowMin: number
  // 下一节：尚未开始且最接近当前时刻的课。
  nextStart: string | null
  nextCourseId: string | null
  nextInMinutes: number | null
}

/** 由合并后的课程块 + 作息表 + 当前时间推导今日时间轴。纯函数，可单测。 */
export function computeTodayTimeline(
  blocks: MergedBlock[],
  periods: LessonPeriod[],
  now: string,
): TodayTimeline {
  const nowMin = toMinutes(now)
  const items: TodayTimelineItem[] = blocks
    .map((b) => {
      const startP = periods.find((p) => p.lesson_no === b.startLesson)
      const endP = periods.find((p) => p.lesson_no === b.endLesson)
      if (!startP || !endP) return null
      const startMin = toMinutes(startP.start_time)
      const endMin = toMinutes(endP.end_time)
      const status: TodayTimelineItem['status'] =
        nowMin >= endMin ? 'done' : nowMin <= startMin ? 'upcoming' : 'ongoing'
      return {
        slotId: b.slotId,
        courseId: b.courseId,
        room: b.room,
        start: startP.start_time,
        end: endP.end_time,
        startMin,
        endMin,
        status,
      }
    })
    .filter((x): x is TodayTimelineItem => x !== null)
    .sort((a, b) => a.startMin - b.startMin)

  const upcoming = items
    .filter((i) => i.status === 'upcoming')
    .sort((a, b) => a.startMin - b.startMin)
  const next = upcoming[0]
  return {
    items,
    nowMin,
    nextStart: next?.start ?? null,
    nextCourseId: next?.courseId ?? null,
    nextInMinutes: next ? next.startMin - nowMin : null,
  }
}

// ---- 内部工具 ----

function parseISO(s: string): Date {
  const d = new Date(`${s}T00:00:00`)
  return Number.isNaN(d.getTime()) ? new Date(0) : d
}

function toISO(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function addDays(d: Date, days: number): Date {
  const out = new Date(d)
  out.setDate(out.getDate() + days)
  return out
}

function minutesBetween(a: string, b: string): number {
  return toMinutes(b) - toMinutes(a)
}

function toMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(':').map(Number)
  return h * 60 + m
}

export const __internal = { parseISO, toISO, addDays, minutesBetween, toMinutes }

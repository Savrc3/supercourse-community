import { describe, expect, it } from 'vitest'

import {
  blockRowSpan,
  bigPeriodLines,
  applyDayOverrides,
  canonicalTermStartDate,
  computeTodayTimeline,
  currentWeek,
  deriveBigPeriodRows,
  lessonTime,
  mergeConsecutive,
  parseWeeks,
  slotInWeek,
  truncateName,
  weekDates,
  weekHeader,
  type CourseSlot,
  type LessonPeriod,
} from './derive'

describe('parseWeeks / slotInWeek', () => {
  it('解析 JSON 周次规则', () => {
    expect(parseWeeks('{"ranges":[[1,16]],"only":[],"except":[],"parity":"all"}')).toEqual({
      ranges: [[1, 16]],
      only: [],
      except: [],
      parity: 'all',
    })
  })

  it('非法 JSON 返回空规则', () => {
    expect(parseWeeks('{bad')).toEqual({ ranges: [], only: [], except: [], parity: 'all' })
  })

  it('单双周过滤：奇数周只显示单周', () => {
    const odd = { ranges: [[1, 16]], only: [], except: [], parity: 'odd' as const }
    expect(slotInWeek(odd, 1)).toBe(true)
    expect(slotInWeek(odd, 2)).toBe(false)
  })

  it('except 剔除指定的周', () => {
    const spec = { ranges: [[1, 16]], only: [], except: [8], parity: 'all' as const }
    expect(slotInWeek(spec, 8)).toBe(false)
    expect(slotInWeek(spec, 9)).toBe(true)
  })

  it('only 精确指定周', () => {
    const spec = { ranges: [], only: [3, 5], except: [], parity: 'all' as const }
    expect(slotInWeek(spec, 3)).toBe(true)
    expect(slotInWeek(spec, 4)).toBe(false)
  })
})

describe('weekDates / currentWeek / weekHeader', () => {
  it('修复旧版演示学期的起始日，保留其它学期日期', () => {
    expect(canonicalTermStartDate({ name: '2026-2027-1', start_date: '2026-09-07' })).toBe('2026-08-31')
    expect(canonicalTermStartDate({ name: '自定义学期', start_date: '2026-09-07' })).toBe('2026-09-07')
  })

  it('第一周日期从周一算', () => {
    const { monday, sunday } = weekDates('2026-08-31', 1)
    expect(monday).toBe('2026-08-31')
    expect(sunday).toBe('2026-09-06')
  })

  it('第二周偏移 7 天', () => {
    const { monday } = weekDates('2026-08-31', 2)
    expect(monday).toBe('2026-09-07')
  })

  it('当前周：9月3日是第 1 周，9月14日是第 3 周', () => {
    expect(currentWeek('2026-08-31', '2026-09-03', 20)).toBe(1)
    expect(currentWeek('2026-08-31', '2026-09-14', 20)).toBe(3)
  })

  it('超出边界钳制到 1..weeks_total', () => {
    expect(currentWeek('2026-08-31', '2026-01-01', 20)).toBe(1)
    expect(currentWeek('2026-08-31', '2027-06-01', 20)).toBe(20)
  })

  it('周日表头含正确标签与日期', () => {
    const head = weekHeader('2026-08-31', 1)
    expect(head).toHaveLength(7)
    expect(head[0]).toMatchObject({ weekday: 1, label: '一', date: '2026-08-31' })
    expect(head[6]).toMatchObject({ weekday: 7, label: '日', date: '2026-09-06' })
  })
})

describe('lessonTime / bigPeriodLines', () => {
  const periods: LessonPeriod[] = [
    { id: 'p1', lesson_no: 1, start_time: '08:00', end_time: '08:45', big_period: 1 },
    { id: 'p2', lesson_no: 2, start_time: '08:45', end_time: '09:30', big_period: 1 },
    { id: 'p3', lesson_no: 3, start_time: '09:40', end_time: '10:25', big_period: 2 },
    { id: 'p4', lesson_no: 4, start_time: '10:25', end_time: '11:10', big_period: 2 },
  ]

  it('小节号映射时间段', () => {
    expect(lessonTime(periods, 1)).toEqual({ start: '08:00', end: '08:45' })
    expect(lessonTime(periods, 99)).toBeNull()
  })

  it('由时间间隙推导大节分隔线', () => {
    const lines = bigPeriodLines(periods)
    // 第2小节后(09:30)到第3小节(09:40)有10分钟间隙
    expect(lines).toEqual([{ afterLesson: 2, gapMinutes: 10 }])
  })
})

describe('mergeConsecutive', () => {
  const slots: CourseSlot[] = [
    // 课程A，第3/4/5小节连堂（周一）
    { id: 's1', course_id: 'cA', weekday: 1, start_lesson: 3, end_lesson: 3, room: 'R1', weeks: '{"ranges":[[1,16]],"only":[],"except":[],"parity":"all"}' },
    { id: 's2', course_id: 'cA', weekday: 1, start_lesson: 4, end_lesson: 4, room: 'R1', weeks: '{"ranges":[[1,16]],"only":[],"except":[],"parity":"all"}' },
    { id: 's3', course_id: 'cA', weekday: 1, start_lesson: 5, end_lesson: 5, room: 'R1', weeks: '{"ranges":[[1,16]],"only":[],"except":[],"parity":"all"}' },
    // 课程B，单周显示（周二）
    { id: 's4', course_id: 'cB', weekday: 2, start_lesson: 1, end_lesson: 2, room: 'R2', weeks: '{"ranges":[[1,16]],"only":[],"except":[],"parity":"odd"}' },
  ]

  it('合并相邻同课程小节为一个跨行长方格', () => {
    const merged = mergeConsecutive(slots, 1)
    const a = merged.find((m) => m.courseId === 'cA')
    expect(a).toBeDefined()
    expect(a?.startLesson).toBe(3)
    expect(a?.endLesson).toBe(5)
  })

  it('单双周过滤：偶数周不显示 cB', () => {
    const merged = mergeConsecutive(slots, 2)
    expect(merged.find((m) => m.courseId === 'cB')).toBeUndefined()
  })

  it('完全相同的课程安排只渲染一次', () => {
    const merged = mergeConsecutive([
      ...slots,
      { ...slots[0], id: 's1-duplicate' },
    ], 1)
    expect(merged.filter((item) => item.courseId === 'cA')).toHaveLength(1)
    expect(merged.find((item) => item.courseId === 'cA')).toMatchObject({ startLesson: 3, endLesson: 5 })
  })
})

describe('applyDayOverrides', () => {
  const blocks = [
    { slotId: 's1', courseId: 'cA', weekday: 1, startLesson: 1, endLesson: 2, room: 'R1', weeks: { ranges: [], only: [], except: [], parity: 'all' as const } },
    { slotId: 's2', courseId: 'cB', weekday: 2, startLesson: 3, endLesson: 3, room: 'R2', weeks: { ranges: [], only: [], except: [], parity: 'all' as const } },
  ]
  const dates = [
    { weekday: 1, date: '2026-08-31' },
    { weekday: 2, date: '2026-09-01' },
  ]

  it('换教室只影响指定日期', () => {
    const result = applyDayOverrides(blocks, dates, [{ day: '2026-08-31', action: 'room', slotId: 's1', room: 'R9' }])
    expect(result.find((item) => item.slotId === 's1')?.room).toBe('R9')
    expect(result.find((item) => item.slotId === 's2')?.room).toBe('R2')
  })

  it('停课移除指定日期的课程块', () => {
    const result = applyDayOverrides(blocks, dates, [{ day: '2026-09-01', action: 'cancel', courseId: 'cB' }])
    expect(result).toHaveLength(1)
    expect(result[0].courseId).toBe('cA')
  })

  it('调课生成目标星期和小节的显示块', () => {
    const result = applyDayOverrides(blocks, dates, [{
      day: '2026-08-31',
      action: 'move',
      slotId: 's1',
      toWeekday: 2,
      toStartLesson: 5,
      toEndLesson: 6,
    }])
    expect(result.find((item) => item.slotId === 's1')).toMatchObject({ weekday: 2, startLesson: 5, endLesson: 6 })
  })
})

  describe('truncateName', () => {
  it('短名不截断', () => {
    expect(truncateName('高等数学', 6)).toBe('高等数学')
  })
  it('长名截断加省略号', () => {
    expect(truncateName('模拟电子技术基础', 6)).toBe('模拟电子技术…')
  })
})

describe('computeTodayTimeline', () => {
  const periods: LessonPeriod[] = [
    { id: 'p1', lesson_no: 1, start_time: '08:00', end_time: '08:50', big_period: 1 },
    { id: 'p2', lesson_no: 2, start_time: '09:00', end_time: '09:50', big_period: 1 },
    { id: 'p3', lesson_no: 3, start_time: '10:10', end_time: '11:00', big_period: 2 },
  ]
  const blocks = [
    { slotId: 's1', courseId: 'cA', weekday: 1, startLesson: 1, endLesson: 1, room: 'R1', weeks: { ranges: [[1, 16]], only: [], except: [], parity: 'all' as const } },
    { slotId: 's2', courseId: 'cB', weekday: 1, startLesson: 3, endLesson: 3, room: 'R2', weeks: { ranges: [[1, 16]], only: [], except: [], parity: 'all' as const } },
  ]

  it('标记进行中 / 未开始 / 已结束', () => {
    const tl = computeTodayTimeline(blocks, periods, '08:20')
    expect(tl.items.find((i) => i.courseId === 'cA')?.status).toBe('ongoing')
    expect(tl.items.find((i) => i.courseId === 'cB')?.status).toBe('upcoming')
  })

  it('当前时间需要按分钟比较，同一节课结束标志', () => {
    const tl = computeTodayTimeline(blocks, periods, '11:30')
    expect(tl.items.every((i) => i.status === 'done')).toBe(true)
  })

  it('下一节倒计时', () => {
    const tl = computeTodayTimeline(blocks, periods, '08:55')
    expect(tl.nextCourseId).toBe('cB')
    expect(tl.nextStart).toBe('10:10')
    expect(tl.nextInMinutes).toBe(75) // 10:10 - 08:55 = 75 分钟
  })

  it('无下一节时 nextStart 为 null', () => {
    const tl = computeTodayTimeline(blocks, periods, '12:00')
    expect(tl.nextStart).toBeNull()
    expect(tl.nextInMinutes).toBeNull()
  })
})

describe('deriveBigPeriodRows / blockRowSpan', () => {
  const periods: LessonPeriod[] = [
    { id: 'p1', lesson_no: 1, start_time: '08:00', end_time: '08:50', big_period: 1 },
    { id: 'p2', lesson_no: 2, start_time: '09:00', end_time: '09:50', big_period: 1 },
    { id: 'p3', lesson_no: 3, start_time: '10:10', end_time: '11:00', big_period: 2 },
    { id: 'p4', lesson_no: 4, start_time: '11:10', end_time: '12:00', big_period: 2 },
    { id: 'p5', lesson_no: 5, start_time: '14:00', end_time: '14:50', big_period: 3 },
  ]

  it('按大节聚合出三行，行区间正确', () => {
    const rows = deriveBigPeriodRows(periods)
    expect(rows).toHaveLength(3)
    expect(rows[0]).toMatchObject({ big: 1, start: '08:00', end: '09:50', firstLesson: 1, lastLesson: 2 })
    expect(rows[1]).toMatchObject({ big: 2, start: '10:10', end: '12:00', firstLesson: 3, lastLesson: 4 })
    expect(rows[2]).toMatchObject({ big: 3, start: '14:00', end: '14:50', firstLesson: 5, lastLesson: 5 })
  })

  it('连堂课跨大节行：第 3-4 节 → 跨大节2 一行', () => {
    const rows = deriveBigPeriodRows(periods)
    const block = { slotId: 's', courseId: 'c', weekday: 1, startLesson: 3, endLesson: 4, room: null, weeks: { ranges: [[1, 16]], only: [], except: [], parity: 'all' as const } }
    expect(blockRowSpan(block, rows)).toEqual({ from: 1, to: 1 })
  })

  it('跨多个大节的课（1-2→3-4 如果连排）映射到 from..to', () => {
    const rows = deriveBigPeriodRows(periods)
    const block = { slotId: 's', courseId: 'c', weekday: 1, startLesson: 1, endLesson: 4, room: null, weeks: { ranges: [[1, 16]], only: [], except: [], parity: 'all' as const } }
    expect(blockRowSpan(block, rows)).toEqual({ from: 0, to: 1 })
  })
})

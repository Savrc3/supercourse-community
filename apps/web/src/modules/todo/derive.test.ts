import { describe, expect, it } from 'vitest'

import type { TodoRow } from '../../db/db'
import { decodeTags, encodeTags, formatDue, isOverdue, sortTodos } from './derive'

function todo(overrides: Partial<TodoRow>): TodoRow {
  return {
    id: overrides.id ?? 'todo',
    _rev: 1,
    _updated_at: null,
    _deleted_at: null,
    course_id: null,
    kind: 'todo',
    title: '待办',
    body: '{}',
    body_text: '',
    due_at: null,
    start_at: null,
    due_all_day: 1,
    repeat: null,
    status: '0',
    done_at: null,
    priority: 1,
    tags: '[]',
    remind_mode: 'inherit',
    remind_offsets: null,
    sort_order: 0,
    created_at: '2026-09-04T00:00:00',
    ...overrides,
  }
}

describe('待办纯逻辑', () => {
  it('标签输入会清理空白并去重', () => {
    expect(encodeTags('作业, 重要，作业,,')).toBe('["作业","重要"]')
    expect(decodeTags('["作业","重要"]')).toEqual(['作业', '重要'])
    expect(decodeTags('作业,重要')).toEqual(['作业', '重要'])
  })

  it('按截止时间排序，无截止时间放最后', () => {
    const sorted = sortTodos([
      todo({ id: 'none' }),
      todo({ id: 'late', due_at: '2026-09-06' }),
      todo({ id: 'early', due_at: '2026-09-05' }),
    ])
    expect(sorted.map((item) => item.id)).toEqual(['early', 'late', 'none'])
  })

  it('格式化全天和带时间截止时间', () => {
    expect(formatDue(todo({ due_at: '2026-09-05', due_all_day: 1 }))).toBe('9月5日 · 全天')
    expect(formatDue(todo({ due_at: '2026-09-05T14:30', due_all_day: 0 }))).toBe('9月5日 14:30')
  })

  it('只把未完成且已过截止时间的待办标记为逾期', () => {
    const now = new Date('2026-09-05T12:00:00')
    expect(isOverdue(todo({ due_at: '2026-09-05', due_all_day: 1 }), now)).toBe(false)
    expect(isOverdue(todo({ due_at: '2026-09-04', due_all_day: 1 }), now)).toBe(true)
    expect(isOverdue(todo({ due_at: '2026-09-04', status: '1' }), now)).toBe(false)
  })
})

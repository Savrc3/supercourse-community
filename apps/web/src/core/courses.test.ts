import { describe, expect, it } from 'vitest'

import { canonicalCourseIds } from './courses'

describe('canonicalCourseIds', () => {
  it('同一学期内资料完全相同的课程只保留一个规范 ID', () => {
    const ids = canonicalCourseIds([
      { id: 'c1', term_id: 't1', name: '模拟电子技术', teacher: '张老师', code: 'C-01', sort_order: 0, _rev: 10 },
      { id: 'c2', term_id: 't1', name: '模拟电子技术', teacher: '张老师', code: 'C-01', sort_order: 1, _rev: 11 },
      { id: 'c3', term_id: 't1', name: '模拟电子技术', teacher: '李老师', code: 'C-01', sort_order: 2, _rev: 12 },
    ])

    expect(ids.get('c1')).toBe('c1')
    expect(ids.get('c2')).toBe('c1')
    expect(ids.get('c3')).toBe('c3')
  })
})

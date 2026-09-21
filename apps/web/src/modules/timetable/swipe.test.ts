import { describe, expect, it } from 'vitest'

import { detectHorizontalSwipe } from './swipe'

describe('detectHorizontalSwipe', () => {
  it('向左移动足够距离表示下一项', () => {
    expect(detectHorizontalSwipe({ x: 220, y: 100 }, { x: 150, y: 106 })).toBe('next')
  })

  it('向右移动足够距离表示上一项', () => {
    expect(detectHorizontalSwipe({ x: 120, y: 100 }, { x: 190, y: 106 })).toBe('previous')
  })

  it('垂直滚动不触发横向切换', () => {
    expect(detectHorizontalSwipe({ x: 120, y: 100 }, { x: 150, y: 190 })).toBeNull()
  })

  it('移动距离过短不触发切换', () => {
    expect(detectHorizontalSwipe({ x: 120, y: 100 }, { x: 155, y: 102 })).toBeNull()
  })
})

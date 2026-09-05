import test from 'node:test'
import assert from 'node:assert/strict'

import state from '../state.cjs'

const { normalizeWindowBounds, readJson } = state

test('窗口尺寸和位置会限制在当前屏幕范围内', () => {
  assert.deepEqual(
    normalizeWindowBounds({ width: 200, height: 2000, x: -500, y: 2000 }, { x: 0, y: 0, width: 1920, height: 1080 }),
    { width: 960, height: 1080, x: 0, y: 0 },
  )
})

test('损坏的窗口状态不会阻止桌面端启动', () => {
  assert.deepEqual(readJson('{bad', { width: 1200 }), { width: 1200 })
  assert.deepEqual(readJson('{"width": 1000}', {}), { width: 1000 })
})

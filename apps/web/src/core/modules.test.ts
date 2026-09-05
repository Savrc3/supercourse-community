import { describe, expect, it } from 'vitest'

import { moduleManifests } from './modules'

describe('模块注册表', () => {
  it('注册了 6 个模块（含隐藏的导入），导航可见 5 个', () => {
    expect(moduleManifests.map((module) => module.id)).toEqual([
      'timetable',
      'timeline',
      'todo',
      'profile',
      'settings',
      'import',
    ])
    const visible = moduleManifests.filter((m) => !m.hidden).map((m) => m.id)
    expect(visible).toEqual(['timetable', 'timeline', 'todo', 'profile', 'settings'])
  })

  it('每条路径唯一且都以 / 开头', () => {
    const paths = moduleManifests.map((module) => module.path)
    expect(new Set(paths).size).toBe(paths.length)
    paths.forEach((path) => expect(path.startsWith('/')).toBe(true))
  })
})

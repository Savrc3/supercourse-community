import { describe, expect, it } from 'vitest'

import { moduleManifests } from './modules'

describe('模块注册表', () => {
  it('主导航只保留课表、待办和设置，导入作为隐藏路由保留', () => {
    expect(moduleManifests.map((module) => module.id)).toEqual([
      'timetable',
      'todo',
      'settings',
      'import',
    ])
    const visible = moduleManifests.filter((m) => !m.hidden).map((m) => m.id)
    expect(visible).toEqual(['timetable', 'todo', 'settings'])
  })

  it('每条路径唯一且都以 / 开头', () => {
    const paths = moduleManifests.map((module) => module.path)
    expect(new Set(paths).size).toBe(paths.length)
    paths.forEach((path) => expect(path.startsWith('/')).toBe(true))
  })
})

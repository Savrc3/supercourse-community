import { beforeEach, describe, expect, it } from 'vitest'

import { defaultRemoteApiBase, getConnectionMode, getConnectionProfile, isSafeRemoteUrl, setConnectionProfile } from './connection'

describe('connection profile', () => {
  beforeEach(() => localStorage.clear())

  it('无配置时默认进入本地模式', () => {
    expect(getConnectionMode()).toBe('local')
    expect(getConnectionProfile()).toBeNull()
  })

  it('远程地址自动规范化为 API 根地址', () => {
    setConnectionProfile({ mode: 'remote', serverUrl: 'https://example.test/' })
    expect(getConnectionProfile()).toEqual({ mode: 'remote', serverUrl: 'https://example.test/api' })
  })

  it('只允许 HTTPS 或本机 HTTP 后端', () => {
    expect(isSafeRemoteUrl('https://example.test/api')).toBe(true)
    expect(isSafeRemoteUrl('http://localhost:8090/api')).toBe(true)
    expect(isSafeRemoteUrl('http://example.test/api')).toBe(false)
  })

  it('没有公开默认后端时使用同源 API', () => {
    expect(defaultRemoteApiBase()).toBe('/api')
  })
})

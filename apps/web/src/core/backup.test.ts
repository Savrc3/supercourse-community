import { describe, expect, it } from 'vitest'

import { restoreLocalBackup } from './backup'

describe('本地备份格式', () => {
  it('拒绝未知格式和版本', async () => {
    await expect(restoreLocalBackup(new Blob([JSON.stringify({ format: 'other', version: 1, tables: {} })]))).rejects.toThrow('格式不受支持')
  })

  it('拒绝过大的备份文件', async () => {
    const file = new Blob([new Uint8Array(50 * 1024 * 1024 + 1)])
    await expect(restoreLocalBackup(file)).rejects.toThrow('不能超过 50MB')
  })
})

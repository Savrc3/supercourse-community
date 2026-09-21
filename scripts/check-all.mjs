#!/usr/bin/env node
// 跨平台质量门禁：Windows 走 scripts/check-all.ps1，Linux/mac 走 scripts/check-all.sh
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const isWin = process.platform === 'win32'
const [cmd, args] = isWin
  ? ['powershell', ['-NoProfile', '-File', join(root, 'scripts', 'check-all.ps1')]]
  : ['bash', [join(root, 'scripts', 'check-all.sh')]]

const result = spawnSync(cmd, args, { stdio: 'inherit', cwd: root })
process.exit(result.status ?? 1)

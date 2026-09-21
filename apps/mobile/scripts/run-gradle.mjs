#!/usr/bin/env node
// 跨平台 Gradle 调用：Windows 用 gradlew.bat，Linux/mac 用 ./gradlew
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const androidRoot = join(dirname(fileURLToPath(import.meta.url)), '..', 'android')
const isWin = process.platform === 'win32'

const result = spawnSync(
  isWin ? 'gradlew.bat' : './gradlew',
  process.argv.slice(2),
  { cwd: androidRoot, stdio: 'inherit', shell: isWin },
)
process.exit(result.status ?? 1)

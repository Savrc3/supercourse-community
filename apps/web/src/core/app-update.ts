import { App } from '@capacitor/app'
import { Capacitor } from '@capacitor/core'
import { Filesystem, Directory } from '@capacitor/filesystem'
import { FileOpener } from '@capacitor-community/file-opener'

import { apiFetch } from './http'

export interface AppUpdateInfo {
  current: string
  latest: string
  url: string | null
  available: boolean
}

export async function checkForAppUpdate(): Promise<AppUpdateInfo> {
  const response = await apiFetch('/version', { cache: 'no-store' })
  if (!response.ok) throw new Error(`version check failed ${response.status}`)
  const data = (await response.json()) as {
    api?: string
    web?: string | null
    android?: string | null
    android_url?: string | null
  }
  const current = Capacitor.isNativePlatform() ? (await App.getInfo()).version : data.web ?? data.api ?? '未知'
  const latest = Capacitor.isNativePlatform() ? data.android ?? data.api ?? current : data.web ?? data.api ?? current
  return { current, latest, url: data.android_url ?? null, available: compareVersions(latest, current) > 0 }
}

export async function downloadAndInstallAndroidUpdate(url: string): Promise<void> {
  if (!Capacitor.isNativePlatform()) throw new Error('仅 Android App 支持安装更新')
  const response = await apiFetch(url)
  if (!response.ok) throw new Error(`download failed ${response.status}`)
  const data = new Uint8Array(await response.arrayBuffer())
  const base64 = toBase64(data)
  const path = 'updates/supercourse.apk'
  await Filesystem.writeFile({ path, data: base64, directory: Directory.Cache, recursive: true })
  const file = await Filesystem.getUri({ path, directory: Directory.Cache })
  await FileOpener.open({ filePath: file.uri, contentType: 'application/vnd.android.package-archive' })
}

function compareVersions(left: string, right: string): number {
  const a = left.split('.').map((part) => Number.parseInt(part, 10) || 0)
  const b = right.split('.').map((part) => Number.parseInt(part, 10) || 0)
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    if ((a[i] ?? 0) !== (b[i] ?? 0)) return (a[i] ?? 0) - (b[i] ?? 0)
  }
  return 0
}

function toBase64(data: Uint8Array): string {
  let binary = ''
  for (let i = 0; i < data.length; i += 0x8000) {
    binary += String.fromCharCode(...data.subarray(i, i + 0x8000))
  }
  return btoa(binary)
}

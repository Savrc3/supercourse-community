import { getVersion } from '@tauri-apps/api/app'
import { isTauri } from '@tauri-apps/api/core'
import { openUrl } from '@tauri-apps/plugin-opener'
import { invoke } from '@tauri-apps/api/core'

type ElectronDesktopBridge = {
  appVersion?: string
  apiBase?: string
  openExternal?: (url: string) => Promise<void> | void
  showMain?: (path?: string) => void
}

function electronBridge(): ElectronDesktopBridge | null {
  return typeof window === 'undefined'
    ? null
    : (window as Window & { desktop?: ElectronDesktopBridge }).desktop ?? null
}

export function isTauriDesktop(): boolean {
  return typeof window !== 'undefined' && isTauri()
}

export function isDesktopShell(): boolean {
  return Boolean(electronBridge()?.appVersion) || isTauriDesktop()
}

export async function getDesktopVersion(): Promise<string | undefined> {
  const bridge = electronBridge()
  if (bridge?.appVersion) return bridge.appVersion
  if (isTauriDesktop()) return getVersion()
  return undefined
}

export async function openDesktopExternal(rawUrl: string): Promise<void> {
  const url = new URL(rawUrl)
  if (url.protocol !== 'https:') throw new Error('只允许打开 HTTPS 链接')
  const bridge = electronBridge()
  if (bridge?.openExternal) {
    await bridge.openExternal(url.toString())
    return
  }
  if (isTauriDesktop()) {
    await openUrl(url.toString())
    return
  }
  throw new Error('当前环境不支持桌面外链')
}

export async function showDesktopMain(path?: string): Promise<void> {
  const bridge = electronBridge()
  if (bridge?.showMain) {
    bridge.showMain(path)
    return
  }
  if (isTauriDesktop()) await invoke('desktop_show_main', { path: path ?? null })
}

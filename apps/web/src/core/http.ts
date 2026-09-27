import { Capacitor } from '@capacitor/core'
import { defaultRemoteApiBase, getConnectionProfile, isLocalMode } from './connection'
import { isTauriDesktop } from './desktop'
import { platformFetch } from './platform-fetch'

const desktopApiBase = typeof window !== 'undefined'
  ? (window as Window & { desktop?: { apiBase?: string } }).desktop?.apiBase
  : undefined

/** Web/PWA 同源；原生壳和自建模式使用用户选择的后端。 */
export function getApiBase(): string {
  const profile = getConnectionProfile()
  if (profile?.mode === 'remote' && profile.serverUrl) return profile.serverUrl
  if (isLocalMode()) return ''
  if (Capacitor.isNativePlatform()) return defaultRemoteApiBase()
  return desktopApiBase || (isTauriDesktop() ? '' : '/api')
}

export const API_BASE = getApiBase()

export function apiUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path
  const base = getApiBase()
  return `${base}${path.startsWith('/') ? path : `/${path}`}`
}

export function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  if (isLocalMode()) {
    return Promise.resolve(new Response(JSON.stringify({ detail: { code: 'local_mode', message: '当前为本地模式' } }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    }))
  }
  return platformFetch(apiUrl(path), init)
}

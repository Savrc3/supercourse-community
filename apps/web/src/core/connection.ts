import { Capacitor } from '@capacitor/core'

export type AppMode = 'local' | 'remote'

export interface ConnectionProfile {
  mode: AppMode
  serverUrl?: string
}

const PROFILE_KEY = 'sc_connection_profile'
const TOKEN_KEY = 'sc_token'
const configuredApiBase = String(import.meta.env.VITE_API_BASE_URL ?? '').trim()

function normalizeServerUrl(value: string): string {
  const raw = value.trim().replace(/\/+$/, '')
  if (!raw) return ''
  return raw.endsWith('/api') ? raw : `${raw}/api`
}

export function getConnectionProfile(): ConnectionProfile | null {
  const raw = localStorage.getItem(PROFILE_KEY)
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as Partial<ConnectionProfile>
      if (parsed.mode === 'local') return { mode: 'local' }
      if (parsed.mode === 'remote' && typeof parsed.serverUrl === 'string') {
        const serverUrl = normalizeServerUrl(parsed.serverUrl)
        if (serverUrl) return { mode: 'remote', serverUrl }
      }
    } catch {
      localStorage.removeItem(PROFILE_KEY)
    }
  }
  if (localStorage.getItem(TOKEN_KEY)) return { mode: 'remote', serverUrl: defaultRemoteApiBase() }
  return null
}

export function getConnectionMode(): AppMode {
  return getConnectionProfile()?.mode ?? 'local'
}

export function defaultRemoteApiBase(): string {
  if (configuredApiBase) return normalizeServerUrl(configuredApiBase)
  const desktopApiBase = typeof window !== 'undefined'
    ? (window as Window & { desktop?: { apiBase?: string } }).desktop?.apiBase
    : undefined
  if (desktopApiBase) return normalizeServerUrl(desktopApiBase)
  return '/api'
}

export function setConnectionProfile(profile: ConnectionProfile): void {
  const normalized: ConnectionProfile = profile.mode === 'local'
    ? { mode: 'local' }
    : { mode: 'remote', serverUrl: normalizeServerUrl(profile.serverUrl ?? defaultRemoteApiBase()) }
  localStorage.setItem(PROFILE_KEY, JSON.stringify(normalized))
}

export function isLocalMode(): boolean {
  return getConnectionMode() === 'local'
}

export function isSafeRemoteUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || ['localhost', 'localhost'].includes(url.hostname)
  } catch {
    return false
  }
}

export function shouldShowSetup(): boolean {
  return !getConnectionProfile() && !Capacitor.isNativePlatform()
}

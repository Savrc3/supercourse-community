import { isTauri } from '@tauri-apps/api/core'
import { fetch as tauriFetch } from '@tauri-apps/plugin-http'

/** Tauri 的 WebView 来源与 API 域名不同，走受能力白名单约束的原生 HTTP 客户端。 */
export function platformFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  if (isTauri()) return tauriFetch(input, init)
  return fetch(input, init)
}

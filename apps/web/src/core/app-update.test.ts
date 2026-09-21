import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  nativeGet: vi.fn(),
  apiFetch: vi.fn(),
  getInfo: vi.fn(),
  isNativePlatform: vi.fn(),
  openExternal: vi.fn(),
  writeFile: vi.fn(),
  getUri: vi.fn(),
  open: vi.fn(),
}))

vi.mock('@capacitor/core', () => ({
  Capacitor: { isNativePlatform: mocks.isNativePlatform },
  CapacitorHttp: { get: mocks.nativeGet },
}))

vi.mock('@capacitor/app', () => ({ App: { getInfo: mocks.getInfo } }))
vi.mock('@capacitor/filesystem', () => ({
  Directory: { Cache: 'CACHE' },
  Filesystem: { writeFile: mocks.writeFile, getUri: mocks.getUri },
}))
vi.mock('@capacitor-community/file-opener', () => ({ FileOpener: { open: mocks.open } }))
vi.mock('./http', () => ({ apiFetch: mocks.apiFetch }))

import { checkForAppUpdate, downloadAndInstallAndroidUpdate, openAppUpdate } from './app-update'

describe('Android 应用更新下载', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.isNativePlatform.mockReturnValue(true)
    mocks.getInfo.mockResolvedValue({ version: '1.0.7' })
    mocks.apiFetch.mockResolvedValue(new Response(new Uint8Array([80, 75, 3, 4]), { status: 200 }))
    mocks.nativeGet.mockResolvedValue({ status: 200, data: 'BASE64_APK' })
    mocks.getUri.mockResolvedValue({ uri: 'content://updates/supercourse.apk' })
    Object.defineProperty(window, 'desktop', { configurable: true, value: undefined, writable: true })
  })

  it('使用原生 HTTP 下载外部 APK，避免 WebView CORS/重定向失败', async () => {
    const url = 'https://github.com/Savrc3/supercourse-community/releases/download/v1.0.8/app-release.apk'

    await downloadAndInstallAndroidUpdate(url)

    expect(mocks.nativeGet).toHaveBeenCalledWith({ url, responseType: 'arraybuffer' })
    expect(mocks.apiFetch).not.toHaveBeenCalledWith(url)
    expect(mocks.writeFile).toHaveBeenCalledWith({
      path: 'updates/supercourse.apk',
      data: 'BASE64_APK',
      directory: 'CACHE',
      recursive: true,
    })
    expect(mocks.open).toHaveBeenCalledWith({
      filePath: 'content://updates/supercourse.apk',
      contentType: 'application/vnd.android.package-archive',
    })
  })

  it('桌面端使用安装包自身版本，并返回桌面安装包地址', async () => {
    mocks.isNativePlatform.mockReturnValue(false)
    mocks.apiFetch.mockResolvedValue(new Response(JSON.stringify({
      api: '1.0.8',
      web: '1.0.8',
      android: '1.0.8',
      android_url: 'https://example.com/app-release.apk',
      desktop: '1.0.8',
      desktop_url: 'https://example.com/Setup.1.0.8.exe',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    Object.defineProperty(window, 'desktop', {
      configurable: true,
      value: { appVersion: '1.0.7', openExternal: mocks.openExternal },
      writable: true,
    })

    const result = await checkForAppUpdate()

    expect(result.current).toBe('1.0.7')
    expect(result.latest).toBe('1.0.8')
    expect(result.url).toBe('https://example.com/Setup.1.0.8.exe')
    expect(result.available).toBe(true)

    if (!result.url) throw new Error('expected desktop update URL')
    await openAppUpdate(result.url)
    expect(mocks.openExternal).toHaveBeenCalledWith('https://example.com/Setup.1.0.8.exe')
  })
})

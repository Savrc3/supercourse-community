import { createPinia } from 'pinia'
import { createApp } from 'vue'
import { App as CapacitorApp } from '@capacitor/app'
import { Capacitor, registerPlugin, type PluginListenerHandle } from '@capacitor/core'
import { LocalNotifications } from '@capacitor/local-notifications'
import { isTauri } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

import App from './App.vue'
import { getConnectionProfile } from './core/connection'
import { startAndroidWidgetMirror } from './core/android-widgets'
import { sync } from './core/sync'
import { router } from './router'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')

if (import.meta.env.MODE === 'tauri') document.title = '课序轻量版'

if (isTauri()) {
  void listen<string>('desktop-navigate', ({ payload }) => {
    void router.push(payload)
  })
}

if (!getConnectionProfile() && !sync.token) {
  void router.replace('/setup')
} else if (Capacitor.isNativePlatform()) {
  if (!localStorage.getItem('sc_onboarding_done')) void router.replace('/onboarding')
  void CapacitorApp.addListener('appStateChange', ({ isActive }) => {
    if (isActive) void sync.syncNow()
  })
  void LocalNotifications.addListener('localNotificationActionPerformed', ({ notification }) => {
    const todoId = notification.extra?.todoId
    if (typeof todoId === 'string') void router.push(`/todo/${todoId}`)
  })
}

// 已登录的设备自启动同步；未登录则等待 /login 页面。
if (sync.token && getConnectionProfile()?.mode === 'remote') {
  sync.start()
}

if (Capacitor.getPlatform() === 'android') {
  interface AndroidWidgetsPlugin {
    saveSnapshot(options: { snapshot: string }): Promise<void>
    getPendingRoute(): Promise<{ route?: string }>
    addListener(eventName: 'widgetNavigate', listener: (event: { route: string }) => void): Promise<PluginListenerHandle>
  }

  const androidWidgets = registerPlugin<AndroidWidgetsPlugin>('AndroidWidgets')
  const isWidgetRoute = (route: unknown): route is string =>
    typeof route === 'string' && (route === '/' || route.startsWith('/courses/') || route.startsWith('/todo/'))

  void (async () => {
    await androidWidgets.addListener('widgetNavigate', ({ route }) => {
      void (async () => {
        const pending = await androidWidgets.getPendingRoute().catch(() => ({ route: '' }))
        const destination = isWidgetRoute(pending.route) ? pending.route : route
        if (isWidgetRoute(destination)) await router.push(destination)
      })()
    })
    await router.isReady()
    const pending = await androidWidgets.getPendingRoute()
    if (isWidgetRoute(pending.route)) await router.push(pending.route)

    const widgetMirror = startAndroidWidgetMirror(
      (snapshot) => androidWidgets.saveSnapshot({ snapshot: JSON.stringify(snapshot) }),
      () => sync.hasUsableLocalSnapshot,
    )
    let mirroredSyncAt = sync.state.lastSyncAt
    sync.subscribe((state) => {
      if (state.lastSyncAt !== null && state.lastSyncAt !== mirroredSyncAt) {
        mirroredSyncAt = state.lastSyncAt
        void widgetMirror.refresh()
      }
    })
    if (mirroredSyncAt !== null) void widgetMirror.refresh()
  })().catch((error: unknown) => {
    console.warn('Android widgets could not be initialized', error)
  })
}

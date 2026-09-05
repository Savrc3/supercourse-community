import { createPinia } from 'pinia'
import { createApp } from 'vue'
import { App as CapacitorApp } from '@capacitor/app'
import { Capacitor } from '@capacitor/core'
import { LocalNotifications } from '@capacitor/local-notifications'

import App from './App.vue'
import { getConnectionProfile } from './core/connection'
import { sync } from './core/sync'
import { router } from './router'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')

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

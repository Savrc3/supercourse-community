import { db } from '../db/db'
import {
  calculateClassReminderTimes,
  calculateReminderTimes,
  mergeReminderConfig,
  type ReminderConfig,
} from '../modules/todo/reminder'
import { Capacitor } from '@capacitor/core'
import { LocalNotifications } from '@capacitor/local-notifications'

const MAX_SCHEDULED = 64
const timers = new Map<string, number>()

type DesktopBridge = {
  notify(payload: { title: string; body: string; todoId?: string }): void
}

function desktopBridge(): DesktopBridge | null {
  const bridge = (window as Window & { desktop?: DesktopBridge }).desktop
  return bridge ?? null
}

export async function requestLocalNotificationPermission(): Promise<NotificationPermission | 'unsupported'> {
  if (Capacitor.isNativePlatform()) {
    const result = await LocalNotifications.requestPermissions()
    return result.display === 'granted' ? 'granted' : result.display === 'denied' ? 'denied' : 'default'
  }
  if (!('Notification' in window)) return 'unsupported'
  return Notification.requestPermission()
}

export async function showSystemNotification(title: string, body: string, todoId?: string): Promise<string> {
  if (Capacitor.isNativePlatform()) {
    const permission = await LocalNotifications.checkPermissions()
    if (permission.display !== 'granted') return '请先允许手机通知'
    await LocalNotifications.createChannel({ id: 'supercourse-reminders', name: '超课表提醒', description: '待办和上课提醒', importance: 5, visibility: 1 })
    await LocalNotifications.schedule({
      notifications: [{ id: Date.now() % 2_000_000_000, title, body, schedule: { at: new Date(Date.now() + 500) }, channelId: 'supercourse-reminders', extra: todoId ? { todoId } : undefined }],
    })
    return '已发送手机系统通知'
  }
  const bridge = desktopBridge()
  if (bridge) {
    bridge.notify({ title, body, todoId })
    return '已发送 Windows 系统通知'
  }
  if (!('Notification' in window)) return '当前环境不支持系统通知'
  if (Notification.permission !== 'granted') {
    const permission = await Notification.requestPermission()
    if (permission !== 'granted') return `通知权限状态：${permission}`
  }
  new Notification(title, { body, tag: todoId ? `todo-${todoId}` : 'supercourse-preview' })
  return '已发送浏览器系统通知'
}

export async function loadReminderConfig(): Promise<ReminderConfig> {
  const row = await db.setting.where('key').equals('reminder.config').first()
  try {
    return mergeReminderConfig(row ? JSON.parse(row.value) : null)
  } catch {
    return mergeReminderConfig(null)
  }
}

export async function startLocalReminderScheduler(): Promise<() => void> {
  if (Capacitor.isNativePlatform()) return startNativeReminderScheduler()
  let stopped = false
  const refresh = async () => {
    const bridge = desktopBridge()
    const browserReady = 'Notification' in window && Notification.permission === 'granted'
    if (stopped || (!bridge && !browserReady)) return
    for (const timer of timers.values()) window.clearTimeout(timer)
    timers.clear()
    const config = await loadReminderConfig()
    const [todos, terms, courses, slots, periods] = await Promise.all([
      db.todo.toArray(), db.term.toArray(), db.course.toArray(), db.course_slot.toArray(), db.lesson_period.toArray(),
    ])
    const todoLocalEnabled = config.channels.todo.includes('mobile') || config.channels.todo.includes('windows')
    const classLocalEnabled = config.channels.class.includes('mobile') || config.channels.class.includes('windows')
    if (!todoLocalEnabled && !classLocalEnabled) return
    const now = new Date()
    const todoItems = todoLocalEnabled
      ? todos.flatMap((todo) => calculateReminderTimes(todo, config, now).map((item) => ({ type: 'todo' as const, ...item, todo })))
      : []
    const classItems = classLocalEnabled
      ? calculateClassReminderTimes(terms, courses, slots, periods, config, now).map((item) => ({ type: 'class' as const, ...item }))
      : []
    const items = [...todoItems, ...classItems].sort((a, b) => a.fireAt.getTime() - b.fireAt.getTime()).slice(0, MAX_SCHEDULED)
    for (const item of items) {
      const key = item.type === 'todo' ? `${item.todo.id}:${item.offset}` : item.id
      const delay = Math.min(Math.max(item.fireAt.getTime() - Date.now(), 0), 2_147_000_000)
      const timer = window.setTimeout(() => {
        if (stopped) return
        if (item.type === 'todo') {
          void showSystemNotification(`超课表：${item.todo.title}`, `${item.todo.course_id ? '课程待办' : '杂事'} · 提前一天提醒`, item.todo.id)
        } else {
          void showSystemNotification(`上课提醒：${item.courseName}`, `${item.room ? `${item.room} · ` : ''}15 分钟后开始`)
        }
        timers.delete(key)
      }, delay)
      timers.set(key, timer)
    }
  }
  await refresh()
  const interval = window.setInterval(() => void refresh(), 60_000)
  return () => {
    stopped = true
    window.clearInterval(interval)
    for (const timer of timers.values()) window.clearTimeout(timer)
    timers.clear()
  }
}

function notificationId(seed: string): number {
  let hash = 0
  for (const char of seed) hash = (hash * 31 + char.charCodeAt(0)) | 0
  return Math.abs(hash) || 1
}

async function startNativeReminderScheduler(): Promise<() => void> {
  let stopped = false
  const refresh = async () => {
    if (stopped) return
    const permission = await LocalNotifications.checkPermissions()
    if (permission.display !== 'granted') return
    const pending = await LocalNotifications.getPending()
    if (pending.notifications.length) await LocalNotifications.cancel({ notifications: pending.notifications.map(({ id }) => ({ id })) })
    const config = await loadReminderConfig()
    const todoMobileEnabled = config.channels.todo.includes('mobile')
    const classMobileEnabled = config.channels.class.includes('mobile')
    if (!todoMobileEnabled && !classMobileEnabled) return
    const [todos, terms, courses, slots, periods] = await Promise.all([
      db.todo.toArray(), db.term.toArray(), db.course.toArray(), db.course_slot.toArray(), db.lesson_period.toArray(),
    ])
    const now = new Date()
    const todoItems = todoMobileEnabled
      ? todos.flatMap((todo) => calculateReminderTimes(todo, config, now).map((item) => ({ type: 'todo' as const, ...item, todo })))
      : []
    const classItems = classMobileEnabled
      ? calculateClassReminderTimes(terms, courses, slots, periods, config, now).map((item) => ({ type: 'class' as const, ...item }))
      : []
    const items = [...todoItems, ...classItems].sort((a, b) => a.fireAt.getTime() - b.fireAt.getTime()).slice(0, MAX_SCHEDULED)
    await LocalNotifications.createChannel({ id: 'supercourse-reminders', name: '超课表提醒', description: '待办和上课提醒', importance: 5, visibility: 1 })
    await LocalNotifications.schedule({
      notifications: items.map((item) => item.type === 'todo'
        ? { id: notificationId(`${item.todo.id}:${item.offset}`), title: `超课表：${item.todo.title}`, body: '提前一天提醒', schedule: { at: item.fireAt }, channelId: 'supercourse-reminders', extra: { todoId: item.todo.id } }
        : { id: notificationId(item.id), title: `上课提醒：${item.courseName}`, body: `${item.room ? `${item.room} · ` : ''}15 分钟后开始`, schedule: { at: item.fireAt }, channelId: 'supercourse-reminders' }),
    })
  }
  await refresh()
  const interval = window.setInterval(() => void refresh(), 60_000)
  return () => { stopped = true; window.clearInterval(interval) }
}

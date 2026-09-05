<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { db } from '../../db/db'
import { sync } from '../../core/sync'
import { apiFetch } from '../../core/http'
import { isLocalMode } from '../../core/connection'
import { requestLocalNotificationPermission, showSystemNotification } from '../../core/notifications'
import { mergeReminderConfig, calculateReminderTimes, type ReminderChannel, type ReminderConfig } from '../todo/reminder'

const channels: Array<{ key: ReminderChannel; label: string }> = [
  { key: 'qq', label: 'QQ' },
  { key: 'mobile', label: '手机通知' },
  { key: 'windows', label: 'Windows 通知' },
]
const config = ref<ReminderConfig>(mergeReminderConfig(null))
const loaded = ref(false)
const saving = ref(false)
const previewing = ref(false)
const qqTesting = ref(false)
const message = ref('')
const error = ref('')
const permission = ref('未请求')

onMounted(() => void load())

async function load() {
  const row = await db.setting.where('key').equals('reminder.config').first()
  try { config.value = mergeReminderConfig(row ? JSON.parse(row.value) : null) } catch { config.value = mergeReminderConfig(null) }
  if ('Notification' in window) permission.value = Notification.permission
  loaded.value = true
}

function toggleChannel(kind: 'todo' | 'class', channel: ReminderChannel, enabled: boolean) {
  const selected = new Set(config.value.channels[kind])
  enabled ? selected.add(channel) : selected.delete(channel)
  config.value.channels[kind] = [...selected]
}

async function save() {
  saving.value = true
  message.value = ''
  error.value = ''
  try {
    const value = JSON.stringify(config.value)
    const row = await db.setting.where('key').equals('reminder.config').first()
    await sync.localWrite('setting', row?.id ?? crypto.randomUUID(), { key: 'reminder.config', value }, row?._rev ?? 0)
    message.value = '提醒设置已保存'
  } catch { error.value = '保存失败，设置仍保留在当前页面' } finally { saving.value = false }
}

async function allowLocal() {
  const result = await requestLocalNotificationPermission()
  permission.value = result
  message.value = result === 'granted' ? '通知权限已允许' : result === 'unsupported' ? '当前环境不支持系统通知' : `通知权限状态：${result}`
}

async function previewNext() {
  if (previewing.value) return
  previewing.value = true
  message.value = ''
  error.value = ''
  try {
    const todos = await db.todo.toArray()
    const next = todos
      .flatMap((todo) => calculateReminderTimes(todo, config.value).map((item) => ({ todo, item })))
      .sort((a, b) => a.item.fireAt.getTime() - b.item.fireAt.getTime())[0]
    if (!next) { message.value = '当前没有可预览的待办提醒，请先创建未完成且设置截止时间的待办'; return }
    message.value = await showSystemNotification(`课序预览：${next.todo.title}`, '这是一次立即弹出的系统通知，不会修改待办。', next.todo.id)
  } catch { error.value = '预览失败，请稍后重试' } finally { previewing.value = false }
}

async function testQQ() {
  if (qqTesting.value) return
  message.value = '正在测试 QQ 通道…'
  error.value = ''
  qqTesting.value = true
  try {
    const response = await apiFetch('/reminders/test-qq', { method: 'POST', headers: sync.token ? { Authorization: `Bearer ${sync.token}` } : {} })
    const data = await response.json().catch(() => ({})) as { detail?: { message?: string } }
    if (!response.ok) throw new Error(data.detail?.message ?? (response.status === 401 ? '请先登录后再测试 QQ' : 'QQ 通道未连通或后端未配置'))
    message.value = 'QQ 测试消息已发送，请查看 QQ'
  } catch (cause) { message.value = ''; error.value = cause instanceof Error ? cause.message : 'QQ 通道未连通或后端未配置' } finally { qqTesting.value = false }
}
</script>

<template>
  <section class="panel reminder-settings">
    <div class="section-head">
      <div>
        <h2>提醒设置</h2>
        <p class="muted">只保留两种提醒：待办截止前一天、上课前 15 分钟。每条待办可单独关闭待办提醒。</p>
      </div>
      <span v-if="loaded" class="state-pill">本地通知：{{ permission }}</span>
    </div>
    <div class="reminder-table">
      <div class="reminder-setting-row">
        <strong>待办</strong>
        <span class="offset-text">截止前一天</span>
        <div class="channel-list">
          <label v-for="channel in channels" :key="channel.key"><input type="checkbox" :checked="config.channels.todo.includes(channel.key)" @change="toggleChannel('todo', channel.key, ($event.target as HTMLInputElement).checked)">{{ channel.label }}</label>
        </div>
      </div>
      <div class="reminder-setting-row">
        <strong>课程</strong>
        <span class="offset-text">上课前 15 分钟</span>
        <div class="channel-list">
          <label v-for="channel in channels" :key="channel.key"><input type="checkbox" :checked="config.channels.class.includes(channel.key)" @change="toggleChannel('class', channel.key, ($event.target as HTMLInputElement).checked)">{{ channel.label }}</label>
        </div>
      </div>
    </div>
    <div class="form-actions reminder-actions">
      <button class="primary-btn" type="button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存提醒设置' }}</button>
      <button class="ghost-btn" type="button" @click="allowLocal">允许系统通知</button>
      <button v-if="!isLocalMode()" class="ghost-btn" type="button" :disabled="qqTesting" @click="testQQ">{{ qqTesting ? '测试中…' : '测试 QQ' }}</button>
      <button class="ghost-btn" type="button" :disabled="previewing" @click="previewNext">{{ previewing ? '发送中…' : '预览系统通知' }}</button>
    </div>
    <p v-if="message" class="feedback success">{{ message }}</p>
    <p v-if="error" class="feedback error">{{ error }}</p>
  </section>
</template>

<style scoped>
.reminder-settings { padding: 18px; }
.section-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.section-head h2 { margin: 0; font-size: 17px; }
.section-head p { margin: 5px 0 0; }
.muted { color: var(--text-secondary); font-size: 12px; line-height: 1.55; }
.state-pill { display: inline-flex; align-items: center; min-height: 30px; padding: 0 10px; border: 1px solid var(--line); border-radius: 999px; background: var(--surface); color: var(--text-secondary); font-size: 12px; white-space: nowrap; }
.reminder-table { display: grid; gap: 10px; }
.reminder-setting-row { display: grid; grid-template-columns: 90px 180px minmax(260px, 1fr); align-items: center; gap: 12px; padding: 13px 0; border-bottom: 1px solid var(--line); }
.offset-text { color: var(--text-secondary); font-size: 13px; }
.channel-list { display: flex; flex-wrap: wrap; gap: 12px; color: var(--text-secondary); font-size: 13px; }
.channel-list label { display: inline-flex; align-items: center; gap: 5px; }
.reminder-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.reminder-actions button { min-height: 38px; padding: 0 13px; border-radius: 8px; font: inherit; font-size: 13px; cursor: pointer; white-space: nowrap; }
.ghost-btn { border: 1px solid var(--line-strong); background: var(--surface); color: var(--text); }
.primary-btn { border: 1px solid var(--accent); background: var(--accent); color: #fff; font-weight: 600; }
.reminder-actions button:disabled { cursor: wait; opacity: .65; }
.feedback { margin: 12px 0 0; padding: 10px 12px; border-radius: 8px; font-size: 13px; }
.feedback.success { color: var(--accent); background: var(--accent-soft); }
.feedback.error { color: var(--danger); background: color-mix(in srgb, var(--danger) 9%, var(--surface)); }
@media (max-width: 760px) { .section-head { flex-direction: column; } .reminder-setting-row { grid-template-columns: 1fr; gap: 7px; } }
</style>

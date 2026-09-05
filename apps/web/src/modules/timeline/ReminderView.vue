<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { db, type CourseRow, type TodoRow } from '../../db/db'
import { sync } from '../../core/sync'
import { apiFetch } from '../../core/http'
import { loadReminderConfig } from '../../core/notifications'
import { calculateReminderTimes, type ReminderConfig } from '../todo/reminder'
import { formatDue, isDoneStatus } from '../todo/derive'

interface ReminderLogRow { id: string; todo_id: string | null; fire_at: string | null; channel: string | null; status: string | null; detail: Record<string, unknown>; created_at: string | null }
const todos = ref<TodoRow[]>([])
const courses = ref<CourseRow[]>([])
const logs = ref<ReminderLogRow[]>([])
const config = ref<ReminderConfig | null>(null)
const now = ref(new Date())
const courseNames = computed(() => new Map(courses.value.map((course) => [course.id, course.name])))
const reminders = computed(() => todos.value
  .filter((todo) => !todo._deleted_at && !isDoneStatus(todo.status) && todo.due_at)
  .map((todo) => ({ todo, next: calculateReminderTimes(todo, config.value ?? undefined, now.value)[0] }))
  .filter((item) => item.next || overdue(item.todo))
  .sort((a, b) => (a.next?.fireAt.getTime() ?? 0) - (b.next?.fireAt.getTime() ?? 0)))

async function load() {
  now.value = new Date()
  ;[todos.value, courses.value, config.value] = await Promise.all([db.todo.toArray(), db.course.toArray(), loadReminderConfig()])
}

let unsubscribe: (() => void) | null = null
onMounted(async () => {
  unsubscribe = sync.subscribe(() => void load())
  await load()
  try {
    const token = localStorage.getItem('sc_token')
    const response = await apiFetch('/reminders/logs', { headers: token ? { Authorization: `Bearer ${token}` } : {} })
    if (response.ok) logs.value = (await response.json() as { logs: ReminderLogRow[] }).logs
  } catch { /* 离线时仍显示本地提醒 */ }
})
onUnmounted(() => unsubscribe?.())

function overdue(todo: TodoRow): boolean {
  if (!todo.due_at) return false
  const due = todo.due_all_day === 1 || !todo.due_at.includes('T') ? new Date(`${todo.due_at.slice(0, 10)}T23:59:59`) : new Date(todo.due_at)
  return due.getTime() < now.value.getTime()
}
function logLabel(status: string | null): string { return status === 'sent' ? '已发送' : status === 'failed' ? '失败' : '等待发送' }
</script>

<template>
  <section class="reminder-view">
    <header class="view-head"><div><h1>提醒展示</h1><p>这里汇总逾期、近期到期项目和最近的发送结果。</p></div><RouterLink
      class="back"
      to="/settings"
    >设置提醒</RouterLink></header>
    <div
      v-if="!reminders.length"
      class="state"
    >暂无需要提醒的项目。</div>
    <RouterLink
      v-for="item in reminders"
      :key="item.todo.id"
      class="reminder-row"
      :class="{ overdue: overdue(item.todo) }"
      :to="`/todo/${item.todo.id}`"
    >
      <div><strong>{{ item.todo.title }}</strong><small>{{ item.todo.course_id ? courseNames.get(item.todo.course_id) : '杂事' }} · {{ formatDue(item.todo) }}</small></div>
      <span>{{ overdue(item.todo) ? '已逾期' : item.next ? `下次 ${item.next.fireAt.toLocaleString('zh-CN', { hour12: false })}` : '请尽快处理' }}</span>
    </RouterLink>
    <section class="log-panel"><h2>最近发送记录</h2><p
      v-if="!logs.length"
      class="state"
    >暂时没有后端发送记录。</p><div
      v-for="log in logs.slice(0, 20)"
      :key="log.id"
      class="log-row"
    ><span>{{ log.fire_at ?? '—' }}</span><span>{{ log.channel ?? '—' }}</span><span :class="{ failed: log.status === 'failed' }">{{ logLabel(log.status) }}</span></div></section>
  </section>
</template>

<style scoped>
.reminder-view { padding-top: 4px; }.back { color: var(--accent); font-size: 13px; }.state { margin-top: 22px; padding: 28px; border: 1px solid var(--line); border-radius: var(--radius); color: var(--text-secondary); text-align: center; }.reminder-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 10px; padding: 14px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); }.reminder-row div { display: grid; gap: 3px; min-width: 0; }.reminder-row strong, .reminder-row small { overflow-wrap: anywhere; }.reminder-row small, .reminder-row > span { color: var(--text-secondary); font-size: 12px; }.reminder-row.overdue { border-color: color-mix(in srgb, var(--danger) 50%, var(--line)); }.reminder-row.overdue > span, .failed { color: var(--danger); }.log-panel { margin-top: 28px; padding-top: 18px; border-top: 1px solid var(--line); }.log-panel h2 { margin: 0 0 10px; font-size: 18px; }.log-row { display: grid; grid-template-columns: minmax(0, 1fr) 100px 90px; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--line); color: var(--text-secondary); font-size: 12px; }.log-row span { overflow-wrap: anywhere; }
@media (max-width: 560px) { .reminder-row { align-items: flex-start; flex-direction: column; }.reminder-row > span { align-self: flex-start; }.log-row { grid-template-columns: 1fr; gap: 3px; } }
</style>

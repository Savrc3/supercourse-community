<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { db } from '../../db/db'
import { sync } from '../../core/sync'
import { apiFetch } from '../../core/http'

const stats = ref<Record<string, unknown> | null>(null)
const local = ref<Record<string, number>>({})
const outbox = ref<Array<{ op_id: string; entity: string; id: string; created_at: string }>>([])
const message = ref('')
onMounted(() => void refresh())
async function refresh() {
  local.value = { term: await db.term.count(), course: await db.course.count(), slot: await db.course_slot.count(), todo: await db.todo.count(), media: await db.media.count(), outbox: await db.outbox.count() }
  outbox.value = (await db.outbox.orderBy('created_at').reverse().limit(20).toArray()).map((item) => ({ op_id: item.op_id, entity: item.entity, id: item.id, created_at: item.created_at }))
  try {
    const response = await apiFetch('/diagnostics', { headers: sync.token ? { Authorization: `Bearer ${sync.token}` } : {} })
    stats.value = response.ok ? await response.json() as Record<string, unknown> : null
  } catch { stats.value = null }
}
async function resync() {
  try { await sync.bootstrap(); message.value = '全量同步完成'; await refresh() } catch { message.value = '同步失败，请确认已绑定且网络可用' }
}
</script>

<template>
  <section class="diagnostics-view"><header class="view-head"><div><h1>诊断</h1><p>查看本地镜像、待传队列和后端提醒调度状态。</p></div><RouterLink
    class="back"
    to="/settings"
  >返回管理</RouterLink></header><section class="panel"><h2>本地镜像</h2><div class="stat-grid"><div
    v-for="(value, key) in local"
    :key="key"
  ><strong>{{ value }}</strong><small>{{ key }}</small></div></div><p>同步状态：{{ sync.state.online ? '在线' : '离线' }} · 待传 {{ sync.state.pending }} · 最新 rev {{ sync.state.latestRev }}</p><div
    v-if="outbox.length"
    class="outbox-list"
  ><strong>最近待传操作</strong><span
    v-for="item in outbox"
    :key="item.op_id"
  >{{ item.created_at }} · {{ item.entity }}/{{ item.id }}</span></div></section><section class="panel"><h2>服务端</h2><p v-if="stats">提醒调度：{{ stats.scheduler_ok ? '运行中' : '未运行' }} · 服务端最新 rev {{ stats.latest_rev }}</p><p
    v-else
    class="muted"
  >后端诊断暂不可用。</p><div class="form-actions"><button
    class="ghost-btn"
    type="button"
    @click="refresh"
  >刷新统计</button><button
    class="primary-btn"
    type="button"
    @click="resync"
  >全量同步</button></div><p
    v-if="message"
    class="feedback success"
  >{{ message }}</p></section></section>
</template>

<style scoped>
.back { color: var(--accent); font-size: 13px; }.panel { margin-top: 16px; }.panel h2 { margin-top: 0; }.stat-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }.stat-grid div { padding: 14px; border: 1px solid var(--line); border-radius: 8px; text-align: center; }.stat-grid strong, .stat-grid small { display: block; }.stat-grid small { margin-top: 4px; color: var(--text-secondary); font-size: 12px; }.outbox-list { display: grid; gap: 5px; margin-top: 12px; color: var(--text-secondary); font-size: 12px; }@media (max-width: 760px) { .stat-grid { grid-template-columns: repeat(3, 1fr); } }@media (max-width: 400px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }
</style>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { sync } from '../../core/sync'
import { apiFetch } from '../../core/http'

interface Conflict { id: string; entity: string | null; row_id: string | null; winner: string | null; created_at: string | null; server_row: Record<string, unknown>; local_row: Record<string, unknown> }
const conflicts = ref<Conflict[]>([])
const error = ref('')
const loading = ref(true)

onMounted(() => void load())
async function load() {
  loading.value = true
  try {
    const response = await apiFetch('/conflicts', { headers: sync.token ? { Authorization: `Bearer ${sync.token}` } : {} })
    if (!response.ok) throw new Error()
    conflicts.value = (await response.json() as { conflicts: Conflict[] }).conflicts
  } catch { error.value = '冲突箱暂时无法读取，请确认已绑定且网络可用' } finally { loading.value = false }
}
async function resolve(item: Conflict, choice: 'server' | 'local') {
  const response = await apiFetch(`/conflicts/${item.id}/resolve`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(sync.token ? { Authorization: `Bearer ${sync.token}` } : {}) }, body: JSON.stringify({ choice }) })
  if (!response.ok) { error.value = '冲突处理失败'; return }
  conflicts.value = conflicts.value.filter((current) => current.id !== item.id)
}
function value(row: Record<string, unknown>, key: string): string { const raw = row[key]; return typeof raw === 'object' ? JSON.stringify(raw) : String(raw ?? '—') }
function keys(item: Conflict): string[] { return [...new Set([...Object.keys(item.server_row), ...Object.keys(item.local_row)])].filter((key) => !['rev', 'updated_at', 'deleted_at'].includes(key)) }
</script>

<template>
  <section class="conflicts-view"><header class="view-head"><div><h1>冲突箱</h1><p>选择保留服务端版本或本地改动，处理后会从列表移除。</p></div><RouterLink
                                    class="back"
                                    to="/settings"
                                  >返回管理</RouterLink></header>
    <p
      v-if="error"
      class="feedback error"
    >{{ error }}</p><div
      v-if="loading"
      class="state"
    >正在读取冲突…</div><div
      v-else-if="!conflicts.length"
      class="state"
    >暂无未解决冲突。</div>
    <article
      v-for="item in conflicts"
      :key="item.id"
      class="conflict-card"
    ><div class="conflict-head"><strong>{{ item.entity }} / {{ item.row_id }}</strong><small>{{ item.created_at }} · 当前胜方：{{ item.winner ?? '—' }}</small></div><div class="diff-table"><div class="diff-row diff-title"><span>字段</span><span>服务端</span><span>本地</span></div><div
      v-for="key in keys(item)"
      :key="key"
      class="diff-row"
    ><code>{{ key }}</code><span>{{ value(item.server_row, key) }}</span><span>{{ value(item.local_row, key) }}</span></div></div><div class="form-actions"><button
      class="ghost-btn"
      type="button"
      @click="resolve(item, 'server')"
    >保留服务端</button><button
      class="primary-btn"
      type="button"
      @click="resolve(item, 'local')"
    >采用本地改动</button></div></article>
  </section>
</template>

<style scoped>
.back { color: var(--accent); font-size: 13px; }.state { margin-top: 22px; padding: 28px; border: 1px solid var(--line); border-radius: var(--radius); color: var(--text-secondary); text-align: center; }.conflict-card { margin-top: 14px; padding: 16px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); }.conflict-head { display: flex; justify-content: space-between; gap: 12px; }.conflict-head small { color: var(--text-secondary); font-size: 12px; }.diff-table { overflow-x: auto; margin-top: 14px; }.diff-row { display: grid; grid-template-columns: 150px minmax(180px, 1fr) minmax(180px, 1fr); gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--line); color: var(--text-secondary); font-size: 12px; }.diff-title { color: var(--text); font-weight: 600; }.diff-row code { color: var(--text); }
</style>

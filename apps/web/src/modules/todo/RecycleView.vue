<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ArrowLeft, RotateCcw, Trash2 } from 'lucide-vue-next'
import { db, type TodoRow } from '../../db/db'
import { sync } from '../../core/sync'

const deletedTodos = ref<TodoRow[]>([])
const loaded = ref(false)
const message = ref('')
async function load() {
  const cutoff = Date.now() - 30 * 24 * 60 * 60 * 1000
  deletedTodos.value = (await db.todo.toArray()).filter((todo) => todo._deleted_at && new Date(todo._deleted_at).getTime() >= cutoff).sort((a, b) => (b._deleted_at ?? '').localeCompare(a._deleted_at ?? ''))
  loaded.value = true
}
async function restore(todo: TodoRow) {
  await sync.localWrite('todo', todo.id, {}, todo._rev, false)
  message.value = `已恢复「${todo.title}」`
  await load()
}
let unsubscribe: (() => void) | null = null
onMounted(() => {
  unsubscribe = sync.subscribe(() => void load())
  void load()
})
onUnmounted(() => unsubscribe?.())
</script>

<template>
  <section class="recycle-view"><header class="view-head"><div><h1>回收站</h1><p>软删除的待办可在这里恢复。</p></div><RouterLink
    class="back"
    to="/todo"
  ><ArrowLeft
    :size="16"
    aria-hidden="true"
  />返回待办</RouterLink></header><p
    v-if="message"
    class="message"
    role="status"
  >{{ message }}</p><div
    v-if="!loaded"
    class="state"
  >正在读取回收站…</div><div
    v-else-if="!deletedTodos.length"
    class="state"
  ><Trash2
    :size="25"
    aria-hidden="true"
  />回收站为空</div><article
    v-for="todo in deletedTodos"
    :key="todo.id"
    class="recycle-row"
  ><div><strong>{{ todo.title }}</strong><small>删除于 {{ todo._deleted_at?.slice(0, 16).replace('T', ' ') }}</small></div><button
    class="restore"
    type="button"
    @click="restore(todo)"
  ><RotateCcw
    :size="15"
    aria-hidden="true"
  />恢复</button></article></section>
</template>

<style scoped>
.recycle-view { padding-top: 4px; }.back { display: inline-flex; align-items: center; gap: 5px; color: var(--accent); font-size: 13px; }.message { margin-top: 14px; color: var(--accent); font-size: 13px; }.state { display: flex; flex-direction: column; align-items: center; gap: 8px; margin-top: 22px; padding: 32px; border: 1px solid var(--line); border-radius: var(--radius); color: var(--text-secondary); text-align: center; }.recycle-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 10px; padding: 14px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); }.recycle-row div { display: grid; gap: 4px; }.recycle-row small { color: var(--text-secondary); font-size: 12px; }.restore { display: inline-flex; align-items: center; gap: 5px; min-height: 34px; padding: 0 10px; border: 1px solid var(--line-strong); border-radius: 7px; background: var(--surface); color: var(--accent); font: inherit; font-size: 12px; cursor: pointer; }
</style>

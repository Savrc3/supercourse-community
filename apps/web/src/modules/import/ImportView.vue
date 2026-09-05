<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { sync } from '../../core/sync'
import { apiFetch } from '../../core/http'

type SlotPreview = {
  course_name: string
  code?: string | null
  weekday: number
  start_lesson: number
  end_lesson: number
  room?: string | null
  weeks: string
}

type DiffItem = {
  kind: 'added' | 'changed' | 'removed'
  index?: number
  row_id?: string
  selected: boolean
  before: SlotPreview | null
  after: SlotPreview | null
}

type DiffGroups = Record<'added' | 'changed' | 'removed', DiffItem[]>

const emptyDiff = (): DiffGroups => ({ added: [], changed: [], removed: [] })
const router = useRouter()
const phase = ref<'idle' | 'uploading' | 'preview' | 'importing' | 'done'>('idle')
const status = ref('')
const warnings = ref<string[]>([])
const errors = ref<string[]>([])
const diff = ref<DiffGroups>(emptyDiff())
const draftId = ref('')
const selectedFile = ref<File | null>(null)
const fileName = ref('')
const expiresAt = ref('')

const diffGroups = computed(() => [
  { kind: 'added' as const, label: '新增', hint: '文件中有，当前学期没有', items: diff.value.added },
  { kind: 'changed' as const, label: '变更', hint: '位置相同，但教室或节数发生变化', items: diff.value.changed },
  { kind: 'removed' as const, label: '删除', hint: '当前学期有，文件中没有（默认不删除）', items: diff.value.removed },
])
const totalChanges = computed(() => diffGroups.value.reduce((total, group) => total + group.items.length, 0))
const selectedCount = computed(() =>
  diffGroups.value.reduce((total, group) => total + group.items.filter((item) => item.selected).length, 0),
)

function onFile(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) {
    selectedFile.value = file
    fileName.value = file.name
    status.value = ''
  }
}

function normalizeItem(raw: Partial<DiffItem>, kind: DiffItem['kind']): DiffItem {
  return {
    kind,
    index: raw.index,
    row_id: raw.row_id,
    selected: raw.selected ?? kind !== 'removed',
    before: raw.before ?? null,
    after: raw.after ?? null,
  }
}

async function upload() {
  if (!selectedFile.value) return
  phase.value = 'uploading'
  status.value = '正在解析…'
  const form = new FormData()
  form.append('file', selectedFile.value)
  try {
    const response = await apiFetch('/import/xls', {
      method: 'POST',
      headers: { Authorization: `Bearer ${sync.token}` },
      body: form,
    })
    const data = await response.json()
    if (!response.ok) {
      status.value = data?.detail?.message || '解析失败'
      phase.value = 'idle'
      return
    }
    draftId.value = data.draft_id
    fileName.value = data.filename || selectedFile.value.name
    expiresAt.value = data.expires_at || ''
    warnings.value = data.warnings ?? []
    errors.value = data.errors ?? []
    diff.value = {
      added: (data.diff?.added ?? []).map((item: Partial<DiffItem>) => normalizeItem(item, 'added')),
      changed: (data.diff?.changed ?? []).map((item: Partial<DiffItem>) => normalizeItem(item, 'changed')),
      removed: (data.diff?.removed ?? []).map((item: Partial<DiffItem>) => normalizeItem(item, 'removed')),
    }
    phase.value = 'preview'
    status.value = ''
  } catch {
    status.value = '网络异常，请重试'
    phase.value = 'idle'
  }
}

async function commit() {
  if (!draftId.value || selectedCount.value === 0) return
  phase.value = 'importing'
  status.value = '正在导入…'
  const accepted = diffGroups.value.flatMap((group) =>
    group.items
      .filter((item) => item.selected)
      .map((item) => ({ kind: item.kind, index: item.index, row_id: item.row_id })),
  )
  try {
    const response = await apiFetch('/import/commit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${sync.token}` },
      body: JSON.stringify({ draft_id: draftId.value, accepted }),
    })
    const data = await response.json()
    if (!response.ok) {
      status.value = data?.detail?.message || '导入失败'
      phase.value = 'preview'
      return
    }
    phase.value = 'done'
    status.value = `已处理 ${data.applied ?? 0} 个写入操作`
  } catch {
    status.value = '网络异常，请重试'
    phase.value = 'preview'
  }
}

function reset() {
  phase.value = 'idle'
  status.value = ''
  selectedFile.value = null
  fileName.value = ''
  diff.value = emptyDiff()
}

function goTimetable() {
  router.push('/')
}

function weekdayLabel(weekday: number) {
  return ['一', '二', '三', '四', '五', '六', '日'][weekday - 1] ?? '?'
}

function weeksLabel(raw: string) {
  try {
    const spec = JSON.parse(raw) as {
      ranges?: number[][]
      only?: number[]
      except?: number[]
      parity?: string
    }
    const parts = (spec.ranges ?? []).map((range) => `${range[0]}-${range[1]}周`)
    parts.push(...(spec.only ?? []).map((week) => `${week}周`))
    if (spec.parity === 'odd') parts.push('单周')
    if (spec.parity === 'even') parts.push('双周')
    if ((spec.except ?? []).length) parts.push(`除${spec.except?.join('、')}周`)
    return parts.join('、') || '全部周'
  } catch {
    return raw || '全部周'
  }
}

function slotSummary(slot: SlotPreview | null) {
  if (!slot) return '无安排详情'
  return `周${weekdayLabel(slot.weekday)} · 第${slot.start_lesson}-${slot.end_lesson}节 · ${slot.room || '无教室'} · ${weeksLabel(slot.weeks)}`
}

function courseName(item: DiffItem) {
  return item.after?.course_name || item.before?.course_name || '未命名课程'
}

function diffKey(item: DiffItem) {
  return `${item.kind}:${item.index ?? item.row_id ?? 'unknown'}`
}
</script>

<template>
  <section class="import">
    <header class="view-head">
      <div>
        <h1>导入课表</h1>
        <p>上传教务导出的 xls / xlsx，先看差异，再逐条确认</p>
      </div>
    </header>

    <div
      v-if="phase === 'idle' || phase === 'uploading'"
      class="panel upload-panel"
    >
      <label class="file-picker">
        <span class="file-label">课表文件</span>
        <span class="file-name">{{ fileName || '选择学生个人课表 .xls / .xlsx' }}</span>
        <input
          type="file"
          accept=".xls,.xlsx"
          :disabled="phase === 'uploading'"
          @change="onFile"
        >
      </label>
      <p class="muted">文件只用于解析预览，确认前不会写入课表。</p>
      <button
        class="primary-btn"
        :disabled="!selectedFile || phase === 'uploading'"
        @click="upload"
      >
        {{ phase === 'uploading' ? '解析中…' : '解析并预览' }}
      </button>
      <p
        v-if="status"
        class="err"
        aria-live="polite"
      >{{ status }}</p>
    </div>

    <div
      v-else-if="phase === 'preview' || phase === 'importing'"
      class="panel preview-panel"
    >
      <div class="preview-head">
        <div>
          <h2>预览差异</h2>
          <p class="muted">{{ fileName }} · draft 有效至 {{ expiresAt || '稍后' }}</p>
        </div>
        <span class="change-count">{{ selectedCount }}/{{ totalChanges }} 项已选</span>
      </div>

      <div
        v-if="warnings.length"
        class="notice warn-box"
      >
        <b>需要留意</b>
        <ul>
          <li
            v-for="(warning, index) in warnings"
            :key="`w-${index}`"
          >{{ warning }}</li>
        </ul>
      </div>
      <div
        v-if="errors.length"
        class="notice err-box"
      >
        <b>解析问题</b>
        <ul>
          <li
            v-for="(error, index) in errors"
            :key="`e-${index}`"
          >{{ error }}</li>
        </ul>
      </div>

      <p
        v-if="totalChanges === 0"
        class="empty-state"
      >这份课表与当前学期没有变化。</p>

      <section
        v-for="group in diffGroups"
        v-else
        :key="group.kind"
        class="diff-group"
      >
        <div class="group-head">
          <div>
            <h3>{{ group.label }} <span>{{ group.items.length }}</span></h3>
            <p class="muted">{{ group.hint }}</p>
          </div>
        </div>
        <ul class="diff-list">
          <li
            v-for="item in group.items"
            :key="diffKey(item)"
            class="diff-item"
            :class="`is-${item.kind}`"
          >
            <label class="diff-check">
              <input
                v-model="item.selected"
                type="checkbox"
                :aria-label="`${item.selected ? '取消' : '选择'}${group.label}${courseName(item)}`"
              >
              <span
                class="check-mark"
                aria-hidden="true"
              />
            </label>
            <div class="diff-body">
              <strong>{{ courseName(item) }}</strong>
              <span class="muted">{{ slotSummary(item.after || item.before) }}</span>
              <span
                v-if="item.kind === 'changed'"
                class="compare"
              >原：{{ slotSummary(item.before) }} → 现：{{ slotSummary(item.after) }}</span>
              <span
                v-else-if="item.kind === 'removed'"
                class="removed-note"
              >文件中未发现，默认不删除</span>
            </div>
          </li>
        </ul>
      </section>

      <div class="actions">
        <button
          class="primary-btn"
          :disabled="phase === 'importing' || selectedCount === 0"
          @click="commit"
        >
          {{ phase === 'importing' ? '导入中…' : `确认导入（${selectedCount}项）` }}
        </button>
        <button
          class="ghost-btn"
          :disabled="phase === 'importing'"
          @click="reset"
        >返回</button>
      </div>
      <p
        v-if="status"
        class="err"
        aria-live="polite"
      >{{ status }}</p>
    </div>

    <div
      v-else
      class="panel done"
    >
      <h2>导入完成</h2>
      <p class="muted">{{ status || '已导入' }}</p>
      <button
        class="primary-btn"
        @click="goTimetable"
      >去看课表</button>
    </div>
  </section>
</template>

<style scoped>
.import {
  padding-top: 4px;
}
.panel {
  margin-top: 18px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
}
.panel h2,
.panel h3 {
  margin: 0;
}
.panel h2 {
  font-size: 17px;
}
.panel h3 {
  font-size: 14px;
}
.muted {
  color: var(--text-secondary);
  font-size: 13px;
}
.file-picker {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 48px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  cursor: pointer;
}
.file-picker:focus-within {
  border-color: var(--accent);
  outline: 2px solid color-mix(in srgb, var(--accent) 22%, transparent);
}
.file-label {
  font-weight: 600;
  white-space: nowrap;
}
.file-name {
  overflow: hidden;
  color: var(--text-secondary);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-picker input {
  width: 1px;
  height: 1px;
  overflow: hidden;
  opacity: 0;
  position: absolute;
}
.primary-btn,
.ghost-btn {
  min-height: 40px;
  padding: 0 16px;
  border-radius: 8px;
  font-weight: 600;
  transition: transform 180ms ease-out, opacity 180ms ease-out;
}
.primary-btn {
  margin-top: 12px;
  border: none;
  background: var(--accent);
  color: #fff;
}
.primary-btn:not(:disabled):hover,
.ghost-btn:not(:disabled):hover {
  transform: translateY(-1px);
}
.primary-btn:disabled,
.ghost-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.ghost-btn {
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text-secondary);
}
.err {
  margin-top: 10px;
  color: var(--danger);
}
.preview-head,
.group-head,
.actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.change-count {
  padding: 5px 9px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.notice {
  margin: 14px 0;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 13px;
}
.warn-box {
  background: var(--accent-soft);
  color: var(--text);
}
.err-box {
  background: color-mix(in srgb, var(--danger) 12%, transparent);
  color: var(--danger);
}
.notice ul {
  margin: 4px 0 0;
  padding-left: 18px;
}
.empty-state {
  margin: 24px 0;
  color: var(--text-secondary);
  text-align: center;
}
.diff-group {
  margin-top: 18px;
}
.group-head {
  align-items: flex-start;
  padding-bottom: 7px;
  border-bottom: 1px solid var(--line-strong);
}
.group-head h3 span {
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 400;
}
.group-head p {
  margin: 3px 0 0;
}
.diff-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.diff-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 11px 0;
  border-bottom: 1px solid var(--line);
}
.diff-item:last-child {
  border-bottom: 0;
}
.diff-check {
  display: grid;
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  place-items: center;
  cursor: pointer;
}
.diff-check input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}
.check-mark {
  width: 18px;
  height: 18px;
  border: 1px solid var(--line-strong);
  border-radius: 5px;
}
.diff-check input:checked + .check-mark {
  border-color: var(--accent);
  background: var(--accent);
  box-shadow: inset 0 0 0 3px var(--surface);
}
.diff-check input:focus-visible + .check-mark {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.diff-body {
  display: grid;
  min-width: 0;
  gap: 3px;
}
.diff-body strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.compare,
.removed-note {
  color: var(--text-secondary);
  font-size: 12px;
}
.removed-note {
  color: var(--danger);
}
.actions {
  justify-content: flex-start;
  margin-top: 18px;
}
.done {
  text-align: center;
}
@media (max-width: 560px) {
  .preview-head,
  .file-picker {
    align-items: flex-start;
    flex-direction: column;
  }
  .file-picker {
    gap: 4px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .primary-btn,
  .ghost-btn {
    transition: none;
  }
}
</style>

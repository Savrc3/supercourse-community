<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Pencil, Save } from 'lucide-vue-next'

import { db, type AttachmentRow, type CourseRow, type CourseSlotRow, type MediaRow, type TodoRow } from '../../db/db'
import { sync } from '../../core/sync'
import { apiFetch, apiUrl } from '../../core/http'
import { isLocalMode } from '../../core/connection'
import { formatDue, isDoneStatus } from '../todo/derive'

const route = useRoute()
const router = useRouter()
const course = ref<CourseRow | null>(null)
const slots = ref<CourseSlotRow[]>([])
const todos = ref<TodoRow[]>([])
const attachments = ref<Array<AttachmentRow & { media?: MediaRow }>>([])
const loaded = ref(false)
const editing = ref(false)
const saving = ref(false)
const message = ref('')
const mediaSources = ref<Record<string, string>>({})
const form = reactive({
  teacher: '',
  textbook: '',
  examAt: '',
  examRoom: '',
  examNote: '',
  gradeBreakdown: '',
  note: '',
})

const openTodos = computed(() => todos.value.filter((todo) => !todo._deleted_at && !isDoneStatus(todo.status)))
const doneTodos = computed(() => todos.value.filter((todo) => !todo._deleted_at && isDoneStatus(todo.status)))
const rooms = computed(() => [...new Set(slots.value.map((slot) => slot.room).filter(Boolean))].join('、'))

let unsubscribeSync: (() => void) | null = null
const localMediaSources = new Map<string, string>()

onMounted(() => {
  unsubscribeSync = sync.subscribe((state) => {
    if (state.lastSyncAt && !editing.value) void load()
  })
  void load()
})

function revokeLocalMediaSources() {
  for (const source of localMediaSources.values()) URL.revokeObjectURL(source)
  localMediaSources.clear()
  mediaSources.value = {}
}

async function resolveMediaSource(media: MediaRow | undefined) {
  if (!media) return ''
  const existing = localMediaSources.get(media.id)
  if (existing) return existing
  if (media.blob) {
    const source = URL.createObjectURL(media.blob)
    localMediaSources.set(media.id, source)
    mediaSources.value = { ...mediaSources.value, [media.id]: source }
    return source
  }
  if (isLocalMode()) return ''
  try {
    const response = await apiFetch(`/media/${media.id}`, {
      headers: { Authorization: `Bearer ${sync.token}` },
    })
    if (!response.ok) return ''
    const source = URL.createObjectURL(await response.blob())
    localMediaSources.set(media.id, source)
    mediaSources.value = { ...mediaSources.value, [media.id]: source }
    return source
  } catch {
    return ''
  }
}

onUnmounted(() => {
  unsubscribeSync?.()
  revokeLocalMediaSources()
})

async function load() {
  revokeLocalMediaSources()
  const row = await db.course.get(String(route.params.id))
  course.value = row ?? null
  if (row) {
    Object.assign(form, {
      teacher: row.teacher ?? '',
      textbook: row.textbook ?? '',
      examAt: row.exam_at ?? '',
      examRoom: row.exam_room ?? '',
      examNote: row.exam_note ?? '',
      gradeBreakdown: row.grade_breakdown ?? '',
      note: row.note ?? '',
    })
    slots.value = (await db.course_slot.toArray()).filter((slot) => slot.course_id === row.id && !slot._deleted_at)
    todos.value = await db.todo.where('course_id').equals(row.id).toArray()
    const links = await db.attachment.where({ owner_type: 'course', owner_id: row.id }).toArray()
    const media = await db.media.bulkGet(links.map((link) => link.media_id))
    attachments.value = links.map((link, index) => ({ ...link, media: media[index] ?? undefined }))
    for (const item of attachments.value) {
      if (item.media) void resolveMediaSource(item.media)
    }
  }
  loaded.value = true
}

function startEdit() {
  message.value = ''
  editing.value = true
}

async function save() {
  if (!course.value || !form.teacher.trim() && !form.textbook.trim() && !form.note.trim() && !form.examAt.trim() && !form.examRoom.trim() && !form.examNote.trim() && !form.gradeBreakdown.trim()) {
    if (!course.value) return
  }
  saving.value = true
  await sync.localWrite('course', course.value.id, {
    teacher: form.teacher.trim() || null,
    textbook: form.textbook.trim() || null,
    exam_at: form.examAt.trim() || null,
    exam_room: form.examRoom.trim() || null,
    exam_note: form.examNote.trim() || null,
    grade_breakdown: form.gradeBreakdown.trim() || null,
    note: form.note.trim() || null,
  }, course.value._rev)
  course.value = { ...course.value, teacher: form.teacher.trim() || null, textbook: form.textbook.trim() || null, exam_at: form.examAt.trim() || null, exam_room: form.examRoom.trim() || null, exam_note: form.examNote.trim() || null, grade_breakdown: form.gradeBreakdown.trim() || null, note: form.note.trim() || null }
  saving.value = false
  editing.value = false
  message.value = '课程资料已保存'
}
</script>

<template>
  <section class="course-detail">
    <div
      v-if="!loaded"
      class="state-card"
    >正在读取课程…</div>
    <div
      v-else-if="!course"
      class="state-card"
    >课程不存在</div>
    <template v-else>
      <header class="detail-head">
        <button
          class="back-btn"
          type="button"
          @click="router.push('/settings')"
        ><ArrowLeft
          :size="17"
          aria-hidden="true"
        />返回管理</button>
        <button
          v-if="!editing"
          class="ghost-btn"
          type="button"
          @click="startEdit"
        ><Pencil
          :size="15"
          aria-hidden="true"
        />编辑资料</button>
      </header>
      <div class="title-row">
        <div>
          <h1>{{ course.name }}</h1>
          <p>{{ [course.teacher, rooms].filter(Boolean).join(' · ') || '暂无教师和教室信息' }}</p>
        </div>
        <span
          v-if="message"
          class="saved"
        ><Save
          :size="14"
          aria-hidden="true"
        />{{ message }}</span>
      </div>

      <form
        v-if="editing"
        class="panel form-grid"
        @submit.prevent="save"
      >
        <label><span>教师</span><input v-model="form.teacher"></label>
        <label><span>教材</span><input v-model="form.textbook"></label>
        <label><span>考试时间</span><input
          v-model="form.examAt"
          placeholder="如 2026-12-20 09:00"
        ></label>
        <label><span>考试地点</span><input v-model="form.examRoom"></label>
        <label class="wide"><span>考试备注</span><textarea
          v-model="form.examNote"
          rows="2"
        /></label>
        <label class="wide"><span>成绩构成</span><textarea
          v-model="form.gradeBreakdown"
          rows="2"
          placeholder="如 平时 40% + 期末 60%"
        /></label>
        <label class="wide"><span>备注</span><textarea
          v-model="form.note"
          rows="3"
        /></label>
        <div class="actions wide"><button
          class="primary-btn"
          type="submit"
          :disabled="saving"
        >{{ saving ? '保存中…' : '保存资料' }}</button><button
          class="ghost-btn"
          type="button"
          @click="editing = false"
        >取消</button></div>
      </form>

      <div
        v-else
        class="detail-grid"
      >
        <section class="panel info-panel">
          <h2>课程资料</h2>
          <dl>
            <dt>教材</dt><dd>{{ course.textbook || '未填写' }}</dd>
            <dt>考试</dt><dd>{{ course.exam_at || '未安排' }}{{ course.exam_room ? ` · ${course.exam_room}` : '' }}</dd>
            <dt>考试备注</dt><dd>{{ course.exam_note || '无' }}</dd>
            <dt>成绩构成</dt><dd>{{ course.grade_breakdown || '未填写' }}</dd>
            <dt>备注</dt><dd>{{ course.note || '无' }}</dd>
          </dl>
        </section>
        <section class="panel">
          <h2>课程待办</h2>
          <p
            v-if="!openTodos.length && !doneTodos.length"
            class="muted"
          >还没有关联待办。</p>
          <RouterLink
            v-for="todo in openTodos"
            :key="todo.id"
            class="todo-row"
            :to="`/todo/${todo.id}`"
          ><span>{{ todo.title }}</span><small>{{ formatDue(todo) }}</small></RouterLink>
          <details
            v-if="doneTodos.length"
            class="done-list"
          ><summary>已完成（{{ doneTodos.length }}）</summary><RouterLink
            v-for="todo in doneTodos"
            :key="todo.id"
            class="todo-row done"
            :to="`/todo/${todo.id}`"
          >{{ todo.title }}</RouterLink></details>
        </section>
        <section class="panel">
          <h2>课程图片</h2>
          <div
            v-if="attachments.length"
            class="media-grid"
          ><img
            v-for="item in attachments"
            :key="item.id"
            :src="item.media ? (mediaSources[item.media.id] || (isLocalMode() ? '' : apiUrl(`/media/${item.media.id}`))) : ''"
            :alt="item.caption || '课程图片'"
          ></div>
          <p
            v-else
            class="muted"
          >还没有课程图片。</p>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.course-detail { padding-top: 4px; }
.detail-head, .title-row, .actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.back-btn, .ghost-btn, .primary-btn { display: inline-flex; align-items: center; gap: 6px; min-height: 38px; padding: 0 13px; border: 1px solid var(--line-strong); border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; font-size: 13px; cursor: pointer; }
.back-btn { border: 0; padding-left: 0; color: var(--text-secondary); }
.primary-btn { border-color: var(--accent); background: var(--accent); color: #fff; font-weight: 600; }
.title-row { margin: 22px 0 16px; align-items: flex-start; }
h1 { margin: 0; font-size: 24px; }
.title-row p, .muted, .saved { color: var(--text-secondary); font-size: 13px; }
.saved { display: inline-flex; align-items: center; gap: 5px; color: var(--accent); }
.panel { padding: 18px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.detail-grid > .panel:last-child { grid-column: 1 / -1; }
h2 { margin: 0 0 14px; font-size: 17px; }
dl { display: grid; grid-template-columns: 90px 1fr; gap: 10px 14px; margin: 0; font-size: 13px; }
dt { color: var(--text-secondary); } dd { margin: 0; white-space: pre-wrap; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px; }
label { display: grid; gap: 5px; color: var(--text-secondary); font-size: 13px; }
label.wide, .wide { grid-column: 1 / -1; }
input, textarea { width: 100%; padding: 9px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; font-size: 13px; }
.todo-row { display: flex; justify-content: space-between; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--line); color: var(--text); font-size: 13px; }
.todo-row small { color: var(--text-secondary); } .todo-row.done { color: var(--text-secondary); text-decoration: line-through; }
.done-list { margin-top: 10px; } summary { color: var(--text-secondary); cursor: pointer; font-size: 13px; }
.media-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 10px; }
.media-grid img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 8px; }
@media (max-width: 700px) { .detail-grid { grid-template-columns: 1fr; } .detail-grid > .panel:last-child { grid-column: auto; } .form-grid { grid-template-columns: 1fr; } label.wide, .wide { grid-column: auto; } }
</style>

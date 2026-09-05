<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Bold, Check, ImagePlus, Link as LinkIcon, List, ListChecks, ListOrdered, Save, X } from 'lucide-vue-next'
import type { JSONContent } from '@tiptap/core'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'
import { Camera, CameraResultType, CameraSource } from '@capacitor/camera'
import { Capacitor } from '@capacitor/core'

import { canonicalCourseIds } from '../../core/courses'
import { apiFetch } from '../../core/http'
import { isLocalMode } from '../../core/connection'
import { sync } from '../../core/sync'
import { db, type CourseRow, type MediaRow, type TermRow, type TodoPriority, type TodoRow, type TodoStatus } from '../../db/db'
import { decodeTags, encodeTags, isDoneStatus, PRIORITY_LABELS } from './derive'
import { EMPTY_TODO_DOC, todoBodyText, parseTodoBody } from './body'
import { compressImage, sha256 } from './media'

const PRIORITY_OPTIONS: { value: TodoPriority; label: string }[] = [
  { value: 2, label: PRIORITY_LABELS[2] },
  { value: 1, label: PRIORITY_LABELS[1] },
  { value: 0, label: PRIORITY_LABELS[0] },
]

interface TodoForm {
  title: string
  courseId: string
  dueDate: string
  dueTime: string
  allDay: boolean
  priority: TodoPriority
  tags: string
  remindEnabled: boolean
}

const route = useRoute()
const router = useRouter()
const todo = ref<TodoRow | null>(null)
const terms = ref<TermRow[]>([])
const courses = ref<CourseRow[]>([])
const loaded = ref(false)
const dirty = ref(false)
const saving = ref(false)
const saveState = ref('')
const error = ref('')
const mediaInput = ref<HTMLInputElement | null>(null)
const pendingMedia = ref(0)
const status = ref<TodoStatus>('0')
const doneAt = ref<string | null>(null)
const form = reactive<TodoForm>(emptyForm())

const editor = useEditor({
  content: EMPTY_TODO_DOC,
  extensions: [
    StarterKit,
    Link.configure({ openOnClick: false, autolink: true }),
    Image.configure({ inline: false, allowBase64: false }),
    TaskList,
    TaskItem.configure({ nested: true }),
  ],
  onUpdate: () => scheduleSave(),
})

const activeTermGroups = computed(() => {
  const availableTerms = terms.value
    .filter((term) => !term._deleted_at && !term.archived_at)
    .sort((a, b) => Number(b.is_current) - Number(a.is_current) || a.start_date.localeCompare(b.start_date))
  return availableTerms.map((term) => {
    const pool = courses.value.filter((course) => course.term_id === term.id && !course._deleted_at)
    const canonicalIds = canonicalCourseIds(pool)
    return {
      term,
      courses: pool
        .filter((course) => canonicalIds.get(course.id) === course.id)
        .sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name)),
    }
  })
})
const courseNames = computed(() => new Map(courses.value.map((course) => [course.id, course.name])))
const done = computed(() => isDoneStatus(status.value))

let saveTimer: ReturnType<typeof setTimeout> | null = null
let unsubscribeSync: (() => void) | null = null

onMounted(() => {
  unsubscribeSync = sync.subscribe((state) => {
    if (state.lastSyncAt && !dirty.value) void load()
  })
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('online', onOnline)
  void load()
})

onUnmounted(() => {
  if (saveTimer) clearTimeout(saveTimer)
  unsubscribeSync?.()
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('online', onOnline)
})

function emptyForm(): TodoForm {
  return { title: '', courseId: '', dueDate: '', dueTime: '', allDay: true, priority: 1, tags: '', remindEnabled: true }
}

async function load() {
  const row = await db.todo.get(String(route.params.id))
  terms.value = await db.term.toArray()
  courses.value = await db.course.toArray()
  if (!row) {
    todo.value = null
    loaded.value = true
    return
  }
  todo.value = row
  status.value = isDoneStatus(row.status) ? '1' : '0'
  doneAt.value = row.done_at
  Object.assign(form, {
    title: row.title,
    courseId: row.course_id ?? '',
    dueDate: row.due_at?.slice(0, 10) ?? '',
    dueTime: row.due_at?.includes('T') ? row.due_at.slice(11, 16) : '',
    allDay: row.due_all_day === 1 || !row.due_at?.includes('T'),
    priority: row.priority,
    tags: decodeTags(row.tags).join('，'),
    remindEnabled: row.remind_mode !== 'off',
  })
  editor.value?.commands.setContent(await localizeBody(parseTodoBody(row.body)), false)
  await flushMediaQueue()
  dirty.value = false
  saveState.value = '已保存'
  error.value = ''
  loaded.value = true
}

function dueValue(): string | null {
  if (!form.dueDate) return null
  return form.allDay ? form.dueDate : `${form.dueDate}T${form.dueTime}`
}

function scheduleSave() {
  if (!loaded.value || !todo.value) return
  dirty.value = true
  saveState.value = '有未保存修改'
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => void saveNow(), 700)
}

async function saveNow() {
  if (!todo.value || !editor.value || saving.value) return
  const title = form.title.trim()
  if (!title) {
    error.value = '标题不能为空'
    saveState.value = '保存失败'
    return
  }
  if (form.dueDate && !form.allDay && !form.dueTime) {
    error.value = '非全天待办请填写截止时间'
    saveState.value = '保存失败'
    return
  }
  saving.value = true
  saveState.value = '正在保存…'
  error.value = ''
  const current = todo.value
  const nextStatus: TodoStatus = status.value === '1' ? '1' : '0'
  const nextDoneAt = nextStatus === '1' ? doneAt.value ?? new Date().toISOString() : null
  const fields = {
    title,
    course_id: form.courseId || null,
    due_at: dueValue(),
    due_all_day: form.dueDate ? (form.allDay ? 1 : 0) : 1,
    priority: form.priority,
    tags: encodeTags(form.tags),
    remind_mode: form.remindEnabled ? 'inherit' : 'off',
    remind_offsets: null,
    status: nextStatus,
    done_at: nextDoneAt,
    body: JSON.stringify(normalizeBody(editor.value.getJSON())),
    body_text: todoBodyText(editor.value.getText({ blockSeparator: '\n' })),
  }
  try {
    await sync.localWrite('todo', current.id, fields, current._rev)
    todo.value = { ...current, ...fields }
    doneAt.value = nextDoneAt
    dirty.value = false
    saveState.value = '已保存'
  } catch {
    saveState.value = '保存失败'
    error.value = '保存失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

function toggleDone() {
  status.value = done.value ? '0' : '1'
  doneAt.value = status.value === '1' ? new Date().toISOString() : null
  scheduleSave()
}

function setLink() {
  if (!editor.value) return
  if (editor.value.isActive('link')) {
    editor.value.chain().focus().unsetLink().run()
    return
  }
  const url = window.prompt('输入链接地址')
  if (url) editor.value.chain().focus().setLink({ href: url }).run()
}

async function chooseImage() {
  if (Capacitor.isNativePlatform()) {
    try {
      const photo = await Camera.getPhoto({
        source: CameraSource.Prompt,
        resultType: CameraResultType.Base64,
        quality: 90,
        correctOrientation: true,
        promptLabelHeader: '添加图片',
        promptLabelPhoto: '从相册选择',
        promptLabelPicture: '拍照',
      })
      if (photo.base64String) {
        const bytes = Uint8Array.from(atob(photo.base64String), (char) => char.charCodeAt(0))
        const file = new File([bytes], `photo-${Date.now()}.${photo.format || 'jpg'}`, { type: 'image/jpeg' })
        await addImageFile(file)
      }
    } catch {
      // 用户取消相机或相册选择时不提示错误。
    }
    return
  }
  mediaInput.value?.click()
}

async function addImage(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  ;(event.target as HTMLInputElement).value = ''
  await addImageFile(file)
}

async function addImageFile(file: File | undefined) {
  if (!file || !file.type.startsWith('image/')) return
  try {
    const image = await compressImage(file)
    const id = crypto.randomUUID()
    const digest = await sha256(image.blob)
    const localUrl = URL.createObjectURL(image.blob)
    localMediaSources.set(localUrl, `media://${id}`)
    const row: MediaRow = {
      id,
      _rev: 0,
      _updated_at: null,
      _deleted_at: null,
      sha256: digest,
      mime: image.mime,
      ext: image.ext,
      bytes: image.blob.size,
      width: image.width,
      height: image.height,
      filename: file.name,
      uploaded: 0,
      created_at: new Date().toISOString(),
      blob: image.blob,
    }
    await db.media.put(row)
    pendingMedia.value += 1
    editor.value?.chain().focus().setImage({ src: localUrl, alt: file.name }).run()
    scheduleSave()
    await uploadLocalMedia(row)
  } catch {
    error.value = '图片处理失败，请重试'
  }
}

function handlePaste(event: ClipboardEvent) {
  const file = [...(event.clipboardData?.files ?? [])].find((item) => item.type.startsWith('image/'))
  if (!file) return
  event.preventDefault()
  void addImageFile(file)
}

async function uploadLocalMedia(row: MediaRow) {
  if (!row.blob) return
  if (isLocalMode()) {
    await db.media.update(row.id, { uploaded: 1 })
    pendingMedia.value = Math.max(0, pendingMedia.value - 1)
    scheduleSave()
    return
  }
  try {
    const result = await sync.uploadMedia(row.id, row.sha256, row.blob, row.filename ?? 'image.jpg')
    await db.media.update(row.id, { uploaded: 1 })
    pendingMedia.value = Math.max(0, pendingMedia.value - 1)
    replaceMediaSource(localMediaUrl(row.id), result.url)
    scheduleSave()
  } catch {
    // 保留 blob 与 media:// 引用，下一次页面加载或联网时重试。
  }
}

async function flushMediaQueue() {
  const queue = await db.media.filter((row) => row.uploaded === 0 && Boolean(row.blob)).toArray()
  pendingMedia.value = queue.length
  for (const row of queue) await uploadLocalMedia(row)
}

const localMediaSources = new Map<string, string>()

function localMediaUrl(id: string): string | undefined {
  for (const [url, source] of localMediaSources) if (source === `media://${id}`) return url
  return undefined
}

function replaceMediaSource(from: string | undefined, to: string) {
  if (!from || !editor.value) return
  editor.value.commands.setContent(mapBody(editor.value.getJSON(), (src) => src === from ? to : src), false)
}

async function localizeBody(doc: JSONContent): Promise<JSONContent> {
  const next: JSONContent = { ...doc }
  if (doc.type === 'image' && typeof doc.attrs?.src === 'string') {
    const source = await resolveImageSource(doc.attrs.src)
    if (!source) {
      return { type: 'paragraph', content: [{ type: 'text', text: '（图片文件已丢失）' }] }
    }
    next.attrs = { ...doc.attrs, src: source }
  }
  if (doc.content) {
    next.content = await Promise.all(doc.content.map((child) => localizeBody(child)))
  }
  return next
}

/** 统一处理本地 media://、需要鉴权的远端媒体和旧版文件名引用。 */
async function resolveImageSource(source: string): Promise<string | null> {
  let mediaId = source.startsWith('media://') ? source.slice('media://'.length) : ''
  if (!mediaId && source.startsWith('/api/media/')) mediaId = source.slice('/api/media/'.length)
  if (!mediaId && !source.includes('://')) {
    const filename = source.split('/').pop()
    const legacy = (await db.media.toArray()).find((row) => row.filename === filename)
    mediaId = legacy?.id ?? ''
  }
  if (!mediaId) return null

  const canonicalSource = `media://${mediaId}`
  const row = await db.media.get(mediaId)
  if (row?.blob) {
    const localUrl = URL.createObjectURL(row.blob)
    localMediaSources.set(localUrl, canonicalSource)
    return localUrl
  }

  try {
    const response = await apiFetch(`/media/${mediaId}`, {
      headers: sync.token ? { Authorization: `Bearer ${sync.token}` } : {},
    })
    if (!response.ok) return null
    const blob = await response.blob()
    if (row) await db.media.update(mediaId, { blob })
    const localUrl = URL.createObjectURL(blob)
    localMediaSources.set(localUrl, canonicalSource)
    return localUrl
  } catch {
    return null
  }
}

function normalizeBody(doc: JSONContent): JSONContent {
  return mapBody(doc, (src) => localMediaSources.get(src) ?? src)
}

function mapBody(doc: JSONContent, mapSource: (source: string) => string): JSONContent {
  const next: JSONContent = { ...doc }
  if (typeof doc.attrs?.src === 'string') next.attrs = { ...doc.attrs, src: mapSource(doc.attrs.src) }
  if (doc.content) next.content = doc.content.map((child) => mapBody(child, mapSource))
  return next
}

async function closeDetail() {
  if (dirty.value) await saveNow()
  await router.push('/todo')
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    void closeDetail()
  }
}

function onOnline() {
  void flushMediaQueue()
}

function courseLabel(courseId: string | null): string {
  return courseId ? courseNames.value.get(courseId) ?? '未知课程' : '杂事'
}

function currentDue(): string {
  if (!form.dueDate) return '未设置截止时间'
  const date = form.dueDate.slice(5).replace('-', '月') + '日'
  return form.allDay ? `${date} · 全天` : `${date} ${form.dueTime}`
}
</script>

<template>
  <section class="todo-detail">
    <div
      v-if="!loaded"
      class="state-card"
    >正在读取待办…</div>

    <div
      v-else-if="!todo"
      class="empty-card"
    >
      <X
        :size="26"
        aria-hidden="true"
      />
      <strong>待办不存在</strong>
      <button
        class="ghost-btn"
        type="button"
        @click="router.push('/todo')"
      >返回待办</button>
    </div>

    <template v-else>
      <div class="detail-head">
        <button
          class="back-btn"
          type="button"
          @click="closeDetail"
        >
          <ArrowLeft
            :size="17"
            aria-hidden="true"
          />
          <span>返回待办</span>
        </button>
        <span
          class="save-state"
          :class="{ error: saveState === '保存失败' }"
          role="status"
        >
          <Save
            :size="14"
            aria-hidden="true"
          />
          {{ saveState }}
        </span>
      </div>

      <div class="detail-layout">
        <article class="editor-panel">
          <div class="editor-title-row">
            <h1>{{ form.title || '未命名待办' }}</h1>
            <span class="context-text">{{ courseLabel(form.courseId) }} · {{ currentDue() }}</span>
          </div>
          <div
            v-if="error"
            class="feedback error"
            role="alert"
          >{{ error }}</div>
          <div
            v-if="editor"
            class="editor-toolbar"
            aria-label="正文格式工具栏"
          >
            <button
              class="toolbar-btn"
              type="button"
              aria-label="粗体"
              :class="{ active: editor.isActive('bold') }"
              @click="editor.chain().focus().toggleBold().run()"
            >
              <Bold
                :size="16"
                aria-hidden="true"
              />
            </button>
            <button
              class="toolbar-btn"
              type="button"
              aria-label="无序列表"
              :class="{ active: editor.isActive('bulletList') }"
              @click="editor.chain().focus().toggleBulletList().run()"
            >
              <List
                :size="17"
                aria-hidden="true"
              />
            </button>
            <button
              class="toolbar-btn"
              type="button"
              aria-label="有序列表"
              :class="{ active: editor.isActive('orderedList') }"
              @click="editor.chain().focus().toggleOrderedList().run()"
            >
              <ListOrdered
                :size="17"
                aria-hidden="true"
              />
            </button>
            <button
              class="toolbar-btn"
              type="button"
              aria-label="勾选清单"
              :class="{ active: editor.isActive('taskList') }"
              @click="editor.chain().focus().toggleTaskList().run()"
            >
              <ListChecks
                :size="17"
                aria-hidden="true"
              />
            </button>
            <button
              class="toolbar-btn"
              type="button"
              aria-label="链接"
              :class="{ active: editor.isActive('link') }"
              @click="setLink"
            >
              <LinkIcon
                :size="16"
                aria-hidden="true"
              />
            </button>
            <button
              class="toolbar-btn"
              type="button"
              aria-label="插入图片"
              @click="chooseImage"
            >
              <ImagePlus
                :size="16"
                aria-hidden="true"
              />
            </button>
          </div>
          <input
            ref="mediaInput"
            class="visually-hidden"
            type="file"
            accept="image/*"
            @change="addImage"
          >
          <EditorContent
            class="editor-content"
            :editor="editor"
            @paste="handlePaste"
          />
          <p class="editor-hint">内容会自动保存，支持粘贴图片，按 Esc 返回列表。{{ pendingMedia ? `待上传图片 ${pendingMedia} 张` : '' }}</p>
        </article>

        <aside class="meta-panel">
          <div class="panel-title">待办信息</div>
          <label class="field wide">
            <span>标题</span>
            <input
              v-model="form.title"
              maxlength="200"
              placeholder="如：完成高数第三章习题"
              @input="scheduleSave"
            >
          </label>

          <label class="field wide">
            <span>所属课程</span>
            <select
              v-model="form.courseId"
              @change="scheduleSave"
            >
              <option value="">杂事（不关联课程）</option>
              <optgroup
                v-for="group in activeTermGroups"
                :key="group.term.id"
                :label="group.term.name"
              >
                <option
                  v-for="course in group.courses"
                  :key="course.id"
                  :value="course.id"
                >{{ course.name }}</option>
              </optgroup>
            </select>
          </label>

          <div class="due-controls">
            <label class="field">
              <span>截止日期</span>
              <input
                v-model="form.dueDate"
                type="date"
                @change="scheduleSave"
              >
            </label>
            <label class="field checkbox-field">
              <input
                v-model="form.allDay"
                type="checkbox"
                @change="scheduleSave"
              >
              <span>全天</span>
            </label>
            <label
              v-if="!form.allDay"
              class="field due-time"
            >
              <span>截止时间</span>
              <input
                v-model="form.dueTime"
                type="time"
                @change="scheduleSave"
              >
            </label>
          </div>

          <label class="field wide">
            <span>优先级</span>
            <select
              :value="form.priority"
              @change="form.priority = Number(($event.target as HTMLSelectElement).value) as TodoPriority; scheduleSave()"
            >
              <option
                v-for="option in PRIORITY_OPTIONS"
                :key="option.value"
                :value="option.value"
              >{{ option.label }}</option>
            </select>
          </label>

          <label class="field wide">
            <span>标签</span>
            <input
              v-model="form.tags"
              placeholder="多个标签用逗号分隔"
              @input="scheduleSave"
            >
          </label>

          <label class="field wide checkbox-field reminder-toggle">
            <span>待办提醒</span>
            <input v-model="form.remindEnabled" type="checkbox" @change="scheduleSave">
            <small class="field-hint">默认在截止前一天提醒；关闭后仅影响这一条待办。</small>
          </label>

          <button
            class="done-toggle"
            type="button"
            :class="{ checked: done }"
            @click="toggleDone"
          >
            <span class="done-check">
              <Check
                v-if="done"
                :size="14"
                aria-hidden="true"
              />
            </span>
            <span>{{ done ? '已完成' : '未完成' }}</span>
            <small v-if="doneAt">{{ doneAt.slice(0, 16).replace('T', ' ') }}</small>
          </button>
        </aside>
      </div>
    </template>
  </section>
</template>

<style scoped>
.todo-detail { padding-top: 4px; }
.state-card, .empty-card { margin-top: 22px; padding: 32px 18px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); color: var(--text-secondary); text-align: center; }
.empty-card { display: flex; flex-direction: column; align-items: center; gap: 8px; }
.empty-card strong { color: var(--text); }
.ghost-btn, .back-btn, .toolbar-btn, .done-toggle { border: 0; font: inherit; cursor: pointer; }
.ghost-btn { min-height: 38px; margin-top: 8px; padding: 0 13px; border: 1px solid var(--line-strong); border-radius: 8px; background: var(--surface); color: var(--text); font-size: 13px; }
.detail-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.back-btn { display: inline-flex; align-items: center; gap: 6px; padding: 6px 0; background: transparent; color: var(--text-secondary); font-size: 13px; }
.back-btn:hover { color: var(--accent); }
.save-state { display: inline-flex; align-items: center; gap: 5px; color: var(--text-secondary); font-size: 12px; }
.save-state.error { color: var(--danger); }
.detail-layout { display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 18px; margin-top: 16px; }
.editor-panel, .meta-panel { min-width: 0; padding: 20px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); }
.editor-title-row { margin-bottom: 16px; }
.editor-title-row h1 { margin: 0; color: var(--text); font-size: 22px; line-height: 1.35; }
.context-text { display: block; margin-top: 5px; color: var(--text-secondary); font-size: 12px; }
.feedback { margin-bottom: 12px; padding: 9px 11px; border-radius: 8px; font-size: 13px; }
.feedback.error { color: var(--danger); background: color-mix(in srgb, var(--danger) 9%, var(--surface)); }
.editor-toolbar { display: flex; gap: 4px; margin-bottom: 10px; padding-bottom: 9px; border-bottom: 1px solid var(--line); }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.toolbar-btn { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 30px; border-radius: 7px; background: transparent; color: var(--text-secondary); }
.toolbar-btn:hover, .toolbar-btn.active { background: var(--accent-soft); color: var(--accent); }
.editor-content { min-height: 360px; }
.editor-content :deep(.ProseMirror) { min-height: 330px; outline: none; color: var(--text); font-size: 15px; line-height: 1.75; }
.editor-content :deep(.ProseMirror p) { margin: 0 0 10px; }
.editor-content :deep(.ProseMirror ul), .editor-content :deep(.ProseMirror ol) { padding-left: 24px; }
.editor-content :deep(.ProseMirror a) { color: var(--accent); text-decoration: underline; }
.editor-content :deep(.ProseMirror img) { display: block; max-width: 100%; height: auto; margin: 12px 0; border-radius: 8px; }
.editor-content :deep(ul[data-type='taskList']) { padding: 0; list-style: none; }
.editor-content :deep(ul[data-type='taskList'] li) { display: flex; align-items: flex-start; gap: 8px; }
.editor-content :deep(ul[data-type='taskList'] li > label) { margin-top: 6px; }
.editor-content :deep(ul[data-type='taskList'] li > div) { flex: 1; }
.editor-hint { margin: 18px 0 0; color: var(--text-secondary); font-size: 12px; }
.panel-title { margin-bottom: 15px; color: var(--text); font-size: 15px; font-weight: 650; }
.field { display: grid; gap: 5px; color: var(--text-secondary); font-size: 13px; }
.field + .field, .due-controls + .field { margin-top: 13px; }
.field input, .field select { width: 100%; min-height: 38px; padding: 0 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; font-size: 13px; }
.field input:focus, .field select:focus { border-color: var(--accent); outline: 2px solid var(--accent-soft); }
.due-controls { display: grid; gap: 9px; margin-top: 13px; }
.checkbox-field { display: flex; align-items: center; justify-content: flex-start; gap: 8px; min-height: 38px; padding: 0 2px; }
.checkbox-field span { order: 2; }
.checkbox-field input { order: 1; }
.checkbox-field input { width: 18px; min-height: 0; height: 18px; padding: 0; accent-color: var(--accent); }
.done-toggle { display: grid; grid-template-columns: 24px 1fr auto; align-items: center; gap: 8px; width: 100%; margin-top: 20px; padding: 10px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); color: var(--text); text-align: left; }
.done-toggle:hover, .done-toggle.checked { border-color: var(--accent); }
.done-check { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; border: 1px solid var(--line-strong); border-radius: 50%; color: #fff; }
.done-toggle.checked .done-check { border-color: var(--accent); background: var(--accent); }
.done-toggle small { color: var(--text-secondary); font-size: 11px; }
@media (max-width: 760px) {
  .detail-layout { grid-template-columns: 1fr; }
  .meta-panel { order: -1; }
}
@media (max-width: 430px) {
  .editor-panel, .meta-panel { padding: 15px; }
  .editor-title-row h1 { font-size: 19px; }
  .editor-content { min-height: 260px; }
  .editor-content :deep(.ProseMirror) { min-height: 230px; }
}
</style>

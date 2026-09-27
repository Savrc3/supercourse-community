<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Check, Plus, Trash2, X } from 'lucide-vue-next'

import { canonicalCourseIds } from '../../core/courses'
import { sync } from '../../core/sync'
import { db, type CourseRow, type TermRow, type TodoRow, type TodoStatus } from '../../db/db'
import TimelineView from '../timeline/TimelineView.vue'
import {
  decodeTags,
  formatDue,
  isDoneStatus,
  isOverdue,
  PRIORITY_LABELS,
  sortTodos,
} from './derive'

const route = useRoute()
const router = useRouter()

interface TodoForm {
  title: string
  courseId: string
  dueDate: string
  dueTime: string
  allDay: boolean
}

const todos = ref<TodoRow[]>([])
const terms = ref<TermRow[]>([])
const courses = ref<CourseRow[]>([])
const loaded = ref(false)
const editorOpen = ref(false)
const message = ref('')
const error = ref('')
const searchText = ref('')
const sortMode = ref<'due' | 'manual'>('due')
const draggedId = ref<string | null>(null)
const undoTodo = ref<TodoRow | null>(null)
const form = reactive<TodoForm>(emptyForm())

const activeTodos = computed(() => {
  const visible = todos.value.filter((todo) => !todo._deleted_at && !isDoneStatus(todo.status) && matchesSearch(todo))
  return sortMode.value === 'manual' ? manualSort(visible) : sortTodos(visible)
})
const completedTodos = computed(() =>
  sortTodos(todos.value.filter((todo) => !todo._deleted_at && isDoneStatus(todo.status) && matchesSearch(todo))),
)
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
const hasTodos = computed(() => activeTodos.value.length > 0 || completedTodos.value.length > 0)
const showingByDate = computed(() => route.query.view === 'date')

function setTodoView(view: 'list' | 'date') {
  void router.replace({
    path: '/todo',
    query: view === 'date' ? { ...route.query, view: 'date' } : {},
  })
}

let unsubscribeSync: (() => void) | null = null
let undoTimer: ReturnType<typeof setTimeout> | null = null
let reloadTimer: ReturnType<typeof setTimeout> | null = null

onMounted(() => {
  unsubscribeSync = sync.subscribeChanges((changes) => {
    if (!changes.some(({ entity }) => ['todo', 'course', 'term'].includes(entity))) return
    if (reloadTimer) clearTimeout(reloadTimer)
    reloadTimer = setTimeout(() => void load(), 120)
  })
  void load()
})

onUnmounted(() => {
  unsubscribeSync?.()
  if (reloadTimer) clearTimeout(reloadTimer)
  if (undoTimer) clearTimeout(undoTimer)
})

function matchesSearch(todo: TodoRow): boolean {
  const query = searchText.value.trim().toLowerCase()
  if (!query) return true
  return [todo.title, todo.body_text, todo.tags, courseLabel(todo.course_id)].some((value) => value.toLowerCase().includes(query))
}

function manualSort(items: TodoRow[]): TodoRow[] {
  return [...items].sort((a, b) => a.sort_order - b.sort_order || a.created_at.localeCompare(b.created_at))
}

function emptyForm(): TodoForm {
  return {
    title: '',
    courseId: '',
    dueDate: '',
    dueTime: '',
    allDay: true,
  }
}

async function load() {
  todos.value = await db.todo.toArray()
  terms.value = (await db.term.toArray()).filter((term) => !term._deleted_at)
  courses.value = await db.course.toArray()
  loaded.value = true
}

function clearFeedback() {
  message.value = ''
  error.value = ''
}

function openCreate() {
  clearFeedback()
  Object.assign(form, emptyForm())
  editorOpen.value = true
}

function closeEditor() {
  editorOpen.value = false
}

function dueValue(): string | null {
  if (!form.dueDate) return null
  if (form.allDay) return form.dueDate
  return `${form.dueDate}T${form.dueTime}`
}

function doneValue(status: TodoStatus, previous: TodoRow | null): string | null {
  return status === '1' ? previous?.done_at ?? new Date().toISOString() : null
}

async function saveTodo() {
  clearFeedback()
  const title = form.title.trim()
  if (!title) {
    error.value = '请填写待办标题'
    return
  }
  if (form.dueDate && !form.allDay && !form.dueTime) {
    error.value = '非全天待办请填写截止时间'
    return
  }
  const fields = {
    course_id: form.courseId || null,
    title,
    due_at: dueValue(),
    due_all_day: form.dueDate ? (form.allDay ? 1 : 0) : 1,
    status: '0' as const,
    done_at: null,
    priority: 1 as const,
    tags: '[]',
    remind_mode: 'inherit',
    remind_offsets: null,
  }
  const id = crypto.randomUUID()
  const createdAt = new Date().toISOString()
  const createdFields = {
    ...fields,
    kind: 'todo',
    body: '{}',
    body_text: '',
    start_at: null,
    repeat: null,
    sort_order: todos.value.length,
    created_at: createdAt,
  }
  const created = {
    ...createdFields,
    id,
    _rev: 0,
    _updated_at: null,
    _deleted_at: null,
  } as TodoRow
  await sync.localWrite('todo', id, createdFields, 0)
  todos.value = [...todos.value, created]
  message.value = '待办已创建'
  closeEditor()
}

async function toggleDone(todo: TodoRow) {
  clearFeedback()
  const status: TodoStatus = isDoneStatus(todo.status) ? '0' : '1'
  const doneAt = doneValue(status, todo)
  await sync.localWrite('todo', todo.id, { status, done_at: doneAt }, todo._rev)
  Object.assign(todo, { status, done_at: doneAt })
}

async function deleteTodo(todo: TodoRow) {
  if (!window.confirm(`确认删除「${todo.title}」吗？`)) return
  clearFeedback()
  await sync.localWrite('todo', todo.id, {}, todo._rev, true)
  undoTodo.value = { ...todo }
  todo._deleted_at = new Date().toISOString()
  if (undoTimer) clearTimeout(undoTimer)
  undoTimer = setTimeout(() => { undoTodo.value = null }, 5000)
  message.value = '待办已删除'
}

async function undoDelete() {
  if (!undoTodo.value) return
  const deleted = undoTodo.value
  await sync.localWrite('todo', deleted.id, {}, deleted._rev, false)
  const restored = todos.value.find((todo) => todo.id === deleted.id)
  if (restored) restored._deleted_at = null
  undoTodo.value = null
  if (undoTimer) clearTimeout(undoTimer)
  message.value = '已撤销删除'
}

function startDrag(todo: TodoRow) {
  draggedId.value = todo.id
}

async function dropTodo(target: TodoRow) {
  const sourceId = draggedId.value
  draggedId.value = null
  if (!sourceId || sourceId === target.id) return
  const ordered = manualSort(activeTodos.value)
  const from = ordered.findIndex((todo) => todo.id === sourceId)
  const to = ordered.findIndex((todo) => todo.id === target.id)
  if (from < 0 || to < 0) return
  const [moved] = ordered.splice(from, 1)
  ordered.splice(to, 0, moved)
  for (const [index, todo] of ordered.entries()) {
    if (todo.sort_order !== index) {
      await sync.localWrite('todo', todo.id, { sort_order: index }, todo._rev)
      todo.sort_order = index
    }
  }
  sortMode.value = 'manual'
}

function courseLabel(courseId: string | null): string {
  return courseId ? courseNames.value.get(courseId) ?? '未知课程' : '杂事'
}

function tagsFor(todo: TodoRow): string[] {
  return decodeTags(todo.tags)
}

function priorityLabel(priority: number): string {
  return PRIORITY_LABELS[priority] ?? PRIORITY_LABELS[1]
}

function priorityClass(priority: number): string {
  return priority === 2 ? 'high' : priority === 0 ? 'low' : 'normal'
}
</script>

<template>
  <section class="todo-view">
    <div class="view-head">
      <div>
        <h1>待办</h1>
        <p v-if="!showingByDate">把要做的事放在一起，离线也能先记下来。</p>
      </div>
      <button
        v-if="!showingByDate"
        class="primary-btn add-btn"
        type="button"
        @click="openCreate"
      >
        <Plus
          :size="17"
          aria-hidden="true"
        />
        <span>新建待办</span>
      </button>
    </div>

    <nav
      class="todo-view-tabs"
      aria-label="待办显示方式"
    >
      <button
        type="button"
        :aria-pressed="!showingByDate"
        :class="{ active: !showingByDate }"
        @click="setTodoView('list')"
      >清单</button>
      <button
        type="button"
        :aria-pressed="showingByDate"
        :class="{ active: showingByDate }"
        @click="setTodoView('date')"
      >按日期</button>
    </nav>

    <TimelineView
      v-if="showingByDate"
      embedded
    />

    <div
      v-if="!showingByDate"
      class="todo-toolbar"
    >
      <label class="search-box">
        <span class="sr-only">搜索待办</span>
        <input
          v-model="searchText"
          type="search"
          placeholder="搜索标题、正文、标签或课程"
        >
      </label>
      <div class="toolbar-group">
        <button
          class="sort-btn"
          :class="{ active: sortMode === 'due' }"
          type="button"
          @click="sortMode = 'due'"
        >按截止时间</button>
        <button
          class="sort-btn"
          :class="{ active: sortMode === 'manual' }"
          type="button"
          @click="sortMode = 'manual'"
        >手动排序</button>
        <RouterLink
          class="recycle-link"
          to="/recycle"
        >回收站</RouterLink>
      </div>
    </div>

    <div
      v-if="!showingByDate && message"
      class="feedback success"
      role="status"
    >
      <span>{{ message }}</span>
      <button
        v-if="undoTodo"
        class="undo-btn"
        type="button"
        @click="undoDelete"
      >撤销</button>
    </div>
    <div
      v-if="!showingByDate && error"
      class="feedback error"
      role="alert"
    >{{ error }}</div>

    <div
      v-if="!showingByDate && !loaded"
      class="state-card"
    >正在读取本地待办…</div>
    <div
      v-if="!showingByDate && loaded && !hasTodos"
      class="empty-card"
    >
      <Check
        :size="26"
        aria-hidden="true"
      />
      <strong>还没有待办</strong>
      <span>先记下一件要做的事吧。</span>
      <button
        class="ghost-btn"
        type="button"
        @click="openCreate"
      >创建第一条</button>
    </div>

    <div
      v-if="!showingByDate && activeTodos.length"
      class="todo-list"
    >
      <article
        v-for="(todo, index) in activeTodos"
        :key="todo.id"
        class="todo-card"
        :class="{ overdue: isOverdue(todo) }"
        draggable="true"
        @dragstart="startDrag(todo)"
        @dragover.prevent
        @drop="dropTodo(todo)"
      >
        <span
          class="todo-index"
          aria-hidden="true"
        >{{ index + 1 < 10 ? '0' + (index + 1) : index + 1 }}</span>
        <button
          class="todo-check"
          type="button"
          :aria-label="`完成：${todo.title}`"
          @click="toggleDone(todo)"
        ><span aria-hidden="true" /></button>
        <RouterLink
          class="todo-content"
          :to="`/todo/${todo.id}`"
        >
          <div class="todo-title-row">
            <h2>{{ todo.title }}</h2>
            <span
              v-if="todo.priority !== 1"
              class="priority-pill"
              :class="priorityClass(todo.priority)"
            >{{ priorityLabel(todo.priority) }}</span>
          </div>
          <div class="todo-meta">
            <span>{{ courseLabel(todo.course_id) }}</span>
            <span :class="{ 'overdue-text': isOverdue(todo) }">{{ formatDue(todo) }}</span>
          </div>
          <div
            v-if="tagsFor(todo).length"
            class="tag-list"
          >
            <span
              v-for="tag in tagsFor(todo)"
              :key="tag"
              class="tag"
            >#{{ tag }}</span>
          </div>
        </RouterLink>
        <button
          class="icon-action danger"
          type="button"
          :aria-label="`删除：${todo.title}`"
          @click="deleteTodo(todo)"
        >
          <Trash2
            :size="16"
            aria-hidden="true"
          />
        </button>
      </article>
    </div>

    <details
      v-if="!showingByDate && completedTodos.length"
      class="completed-section"
    >
      <summary>已完成（{{ completedTodos.length }}）</summary>
      <div class="todo-list completed-list">
        <article
          v-for="(todo, index) in completedTodos"
          :key="todo.id"
          class="todo-card completed"
        >
          <span
            class="todo-index"
            aria-hidden="true"
          >{{ index + 1 < 10 ? '0' + (index + 1) : index + 1 }}</span>
          <button
            class="todo-check checked"
            type="button"
            :aria-label="`恢复：${todo.title}`"
            @click="toggleDone(todo)"
          >
            <Check
              :size="15"
              aria-hidden="true"
            />
          </button>
          <RouterLink
            class="todo-content"
            :to="`/todo/${todo.id}`"
          >
            <div class="todo-title-row"><h2>{{ todo.title }}</h2></div>
            <div class="todo-meta">
              <span>{{ courseLabel(todo.course_id) }}</span>
              <span>{{ formatDue(todo) }}</span>
              <span v-if="todo.done_at">完成于 {{ todo.done_at.slice(0, 16).replace('T', ' ') }}</span>
            </div>
          </RouterLink>
          <button
            class="icon-action danger"
            type="button"
            :aria-label="`删除：${todo.title}`"
            @click="deleteTodo(todo)"
          >
            <Trash2
              :size="16"
              aria-hidden="true"
            />
          </button>
        </article>
      </div>
    </details>

    <div
      v-if="!showingByDate && editorOpen"
      class="dialog-backdrop"
      @click.self="closeEditor"
    >
      <form
        class="todo-dialog"
        @submit.prevent="saveTodo"
      >
        <div class="dialog-head">
          <h2>新建待办</h2>
          <button
            class="close-btn"
            type="button"
            aria-label="关闭"
            @click="closeEditor"
          >
            <X
              :size="19"
              aria-hidden="true"
            />
          </button>
        </div>

        <label class="field wide">
          <span>标题</span>
          <input
            v-model="form.title"
            autofocus
            required
            maxlength="200"
            placeholder="如：完成高数第三章习题"
          >
        </label>

        <div class="form-grid">
          <label class="field">
            <span>所属课程</span>
            <select v-model="form.courseId">
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

          <label class="field">
            <span>截止日期</span>
            <input
              v-model="form.dueDate"
              type="date"
            >
          </label>

          <label class="field checkbox-field">
            <span>全天</span>
            <input
              v-model="form.allDay"
              type="checkbox"
            >
          </label>

          <label
            v-if="!form.allDay"
            class="field"
          >
            <span>截止时间</span>
            <input
              v-model="form.dueTime"
              type="time"
            >
          </label>

        </div>

        <div class="dialog-actions">
          <button
            class="ghost-btn"
            type="button"
            @click="closeEditor"
          >取消</button>
          <button
            class="primary-btn"
            type="submit"
          >保存</button>
        </div>
      </form>
    </div>
  </section>
</template>

<style scoped>
.todo-view { padding-top: 4px; }
.todo-view-tabs { display: flex; gap: 18px; margin: 14px 0 18px; border-bottom: 1px solid var(--line); }
.todo-view-tabs button { min-height: 38px; padding: 0 2px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--text-secondary); font: inherit; cursor: pointer; }
.todo-view-tabs button.active { border-bottom-color: var(--accent); color: var(--accent); font-weight: 600; }
.add-btn, .primary-btn, .ghost-btn, .icon-action, .close-btn, .todo-check { border: 0; font: inherit; cursor: pointer; }
.add-btn, .primary-btn, .ghost-btn { min-height: 38px; padding: 0 13px; border-radius: 8px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; font-size: 13px; }
.primary-btn { background: var(--accent); color: var(--on-accent); font-weight: 600; }
.ghost-btn { border: 1px solid var(--line-strong); background: var(--surface); color: var(--text); }
.primary-btn:hover, .ghost-btn:hover, .icon-action:hover, .close-btn:hover { filter: brightness(0.97); }
.feedback { margin-top: 14px; padding: 10px 12px; border-radius: 8px; font-size: 13px; }
.feedback.success { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.undo-btn { border: 0; background: transparent; color: var(--accent); font: inherit; cursor: pointer; }
.feedback.success { color: var(--accent); background: var(--accent-soft); }
.feedback.error { color: var(--danger); background: color-mix(in srgb, var(--danger) 9%, var(--surface)); }
.state-card, .empty-card { margin-top: 22px; padding: 32px 18px; border: 1px solid var(--line); border-radius: 3px; background: var(--surface); color: var(--text-secondary); text-align: center; }
.empty-card { display: flex; flex-direction: column; align-items: center; gap: 8px; }
.empty-card svg { color: var(--accent); }
.empty-card strong { color: var(--text); }
.empty-card .ghost-btn { margin-top: 8px; }
.todo-list { display: flex; flex-direction: column; gap: 0; margin-top: 22px; border-top: 1px solid var(--line-strong); }
.todo-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 18px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
.search-box { flex: 1; max-width: 420px; }
.search-box input { width: 100%; min-height: 38px; padding: 0 11px; border: 1px solid var(--line); border-radius: 3px; background: var(--surface); color: var(--text); font: inherit; font-size: 13px; }
.toolbar-group { display: flex; align-items: center; gap: 5px; }
.sort-btn, .recycle-link { min-height: 32px; padding: 0 9px; border: 1px solid var(--line); border-radius: 3px; background: var(--surface); color: var(--text-secondary); font: inherit; font-size: 12px; cursor: pointer; }
.sort-btn.active, .sort-btn:hover, .recycle-link:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.recycle-link { display: inline-flex; align-items: center; }
.todo-card { display: grid; grid-template-columns: 28px 24px minmax(0, 1fr) 34px; align-items: center; gap: 6px; min-height: 74px; padding: 12px 2px; border: 0; border-bottom: 1px solid var(--line); border-radius: 0; background: transparent; transition: background-color 180ms ease-out; }
.todo-card:hover { background: color-mix(in srgb, var(--text) 3%, var(--bg)); }
.todo-card.overdue .todo-index { color: var(--danger); }
.todo-card.completed .todo-title-row h2, .todo-card.completed .todo-meta { color: var(--text-secondary); }
.todo-index { color: var(--accent); font: 700 12px/1 var(--font-editorial); font-variant-numeric: tabular-nums; text-align: left; }
.todo-check { width: 20px; height: 20px; flex: 0 0 20px; display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--line-strong); border-radius: 2px; background: transparent; color: var(--on-accent); }
.todo-check:hover { border-color: var(--accent); }
.todo-check.checked { border-color: var(--accent); background: var(--accent); }
.todo-content { min-width: 0; flex: 1; color: inherit; text-decoration: none; }
.todo-content:hover .todo-title-row h2 { color: var(--accent); }
.todo-title-row, .todo-meta, .tag-list, .dialog-head, .dialog-actions { display: flex; align-items: center; }
.todo-title-row { gap: 8px; }
.todo-title-row h2 { min-width: 0; overflow: hidden; margin: 0; color: var(--text); font-size: 15px; font-weight: 650; text-overflow: ellipsis; }
.todo-meta { flex-wrap: wrap; gap: 5px 12px; margin-top: 7px; color: var(--text-secondary); font-size: 12px; }
.todo-meta span + span::before { content: '·'; margin-right: 12px; color: var(--line-strong); }
.overdue-text { color: var(--danger); font-weight: 600; }
.priority-pill, .tag { display: inline-flex; align-items: center; min-height: 20px; padding: 1px 5px; border-radius: 2px; font-size: 11px; white-space: nowrap; }
.priority-pill { border-bottom: 1px solid currentColor; }
.priority-pill.high { color: var(--danger); background: transparent; }
.priority-pill.normal { color: var(--warning); background: transparent; }
.priority-pill.low { color: var(--success); background: transparent; }
.tag-list { flex-wrap: wrap; gap: 5px; margin-top: 7px; }
.tag { color: var(--text-secondary); background: var(--surface-raised); }
.field input, .field select { min-height: 38px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; font-size: 13px; }
.icon-action, .close-btn { width: 34px; height: 34px; flex: 0 0 34px; display: inline-flex; align-items: center; justify-content: center; border-radius: 3px; background: transparent; color: var(--text-secondary); }
.icon-action.danger { color: var(--danger); }
.completed-section { margin-top: 22px; border-top: 1px solid var(--line); padding-top: 14px; }
.completed-section summary { color: var(--text-secondary); cursor: pointer; font-size: 13px; }
.completed-list { margin-top: 12px; }
.dialog-backdrop { position: fixed; inset: 0; z-index: 40; display: flex; align-items: center; justify-content: center; padding: 20px; background: rgba(0, 0, 0, 0.28); }
.todo-dialog { width: min(100%, 560px); max-height: calc(100svh - 40px); overflow: auto; padding: 20px; border: 1px solid var(--line-strong); border-radius: 4px; background: var(--surface); box-shadow: var(--shadow); }
.dialog-head { justify-content: space-between; gap: 10px; margin-bottom: 18px; }
.dialog-head h2 { margin: 0; font-size: 18px; }
.close-btn { border: 1px solid var(--line); }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px; margin-top: 13px; }
.field { display: grid; gap: 5px; color: var(--text-secondary); font-size: 13px; }
.field.wide { grid-column: 1 / -1; }
.field input, .field select { width: 100%; padding: 0 10px; }
.field input:focus, .field select:focus { border-color: var(--accent); outline: 2px solid var(--accent-soft); }
.checkbox-field { display: flex; align-items: center; justify-content: space-between; min-height: 38px; padding: 0 10px; border: 1px solid var(--line); border-radius: 8px; }
.checkbox-field input { width: 18px; height: 18px; min-height: 0; accent-color: var(--accent); }
.dialog-actions { justify-content: flex-end; gap: 8px; margin-top: 20px; }
@media (max-width: 620px) {
  .view-head { flex-direction: column; }
  .add-btn { align-self: flex-start; }
  .todo-card { grid-template-columns: 23px 22px minmax(0, 1fr) 30px; gap: 4px; }
  .todo-index { font-size: 11px; }
  .todo-title-row { align-items: flex-start; flex-wrap: wrap; }
  .todo-title-row h2 { white-space: normal; }
  .form-grid { grid-template-columns: 1fr; }
  .field.wide { grid-column: auto; }
  .todo-toolbar { align-items: stretch; flex-direction: column; }
  .search-box { max-width: none; }
  .toolbar-group { flex-wrap: wrap; }
}
</style>

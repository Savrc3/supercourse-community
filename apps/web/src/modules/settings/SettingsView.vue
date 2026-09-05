<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'

import { db, type CourseRow, type CourseSlotRow, type TermRow, type TimetableOverrideRow } from '../../db/db'
import { sync } from '../../core/sync'
import { createLocalBackup, restoreLocalBackup } from '../../core/backup'
import { canonicalCourseIds } from '../../core/courses'
import { isLocalMode } from '../../core/connection'
import { useAppStore } from '../../stores/app'
import ReminderSettingsPanel from './ReminderSettingsPanel.vue'

const PALETTE = [
  '#D9542B',
  '#2E7FB8',
  '#3B8B47',
  '#A63B91',
  '#C98A12',
  '#5D529B',
  '#12817F',
  '#9E3A4A',
]
const appStore = useAppStore()
const DAY_NAMES = ['一', '二', '三', '四', '五', '六', '日']

const terms = ref<TermRow[]>([])
const courses = ref<CourseRow[]>([])
const slots = ref<CourseSlotRow[]>([])
const overrides = ref<TimetableOverrideRow[]>([])
const selectedTermId = ref('')
const loaded = ref(false)
const message = ref('')
const error = ref('')
const editingCourseId = ref<string | null>(null)
const courseEditorOpen = ref(false)
const editingOverrideId = ref<string | null>(null)
const backupInput = ref<HTMLInputElement | null>(null)
const backupBusy = ref(false)
const backupMessage = ref('')

const termForm = reactive({
  name: '',
  label: '',
  startDate: '',
  weeksTotal: 20,
})
const courseForm = reactive({
  name: '',
  shortName: '',
  teacher: '',
  code: '',
  color: 0,
  credit: '',
})
const overrideForm = reactive({
  slotId: '',
  day: todayISO(),
  action: 'room' as 'room' | 'cancel' | 'move',
  room: '',
  toWeekday: 1,
  toStartLesson: 1,
  toEndLesson: 2,
  note: '',
})

const activeTerm = computed(() => terms.value.find((term) => term.id === selectedTermId.value) ?? null)
const activeCoursePool = computed(() =>
  courses.value.filter((course) => course.term_id === selectedTermId.value && !course._deleted_at),
)
const canonicalCourseIdMap = computed(() => canonicalCourseIds(activeCoursePool.value))
const activeCourses = computed(() =>
  activeCoursePool.value
    .filter((course) => canonicalCourseIdMap.value.get(course.id) === course.id)
    .sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name)),
)
const activeSlots = computed(() =>
  slots.value.filter(
    (slot) =>
      !slot._deleted_at &&
      activeCourses.value.some((course) => course.id === slot.course_id),
  ),
)
const activeOverrides = computed(() =>
  overrides.value
    .filter((item) => item.term_id === selectedTermId.value && !item._deleted_at)
    .sort((a, b) => a.day.localeCompare(b.day)),
)
const slotOptions = computed(() =>
  activeSlots.value.map((slot) => {
    const course = courses.value.find((item) => item.id === slot.course_id)
    return {
      ...slot,
      label: `${course?.name ?? '未知课程'} · 周${DAY_NAMES[slot.weekday - 1]} · 第${slot.start_lesson}-${slot.end_lesson}节${slot.room ? ` · ${slot.room}` : ''}`,
    }
  }),
)

let unsubscribeSync: (() => void) | null = null

onMounted(() => {
  unsubscribeSync = sync.subscribe((state) => {
    if (state.lastSyncAt) void load()
  })
  void load()
})

onUnmounted(() => unsubscribeSync?.())

async function load() {
  terms.value = (await db.term.toArray()).filter((term) => !term._deleted_at)
  courses.value = await db.course.toArray()
  slots.value = await db.course_slot.toArray()
  overrides.value = await db.timetable_override.toArray()
  const current = terms.value.find((term) => term.is_current === 1) ?? terms.value[0]
  const selected = terms.value.find((term) => term.id === selectedTermId.value) ?? current
  if (selected) {
    selectedTermId.value = selected.id
    appStore.setSelectedTerm(selected.id)
    fillTermForm(selected)
  }
  loaded.value = true
}

function todayISO(): string {
  const date = new Date()
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function clearFeedback() {
  message.value = ''
  error.value = ''
}

function fillTermForm(term: TermRow) {
  Object.assign(termForm, {
    name: term.name,
    label: term.label ?? '',
    startDate: term.start_date,
    weeksTotal: term.weeks_total,
  })
}

function selectTerm(id: string) {
  const term = terms.value.find((item) => item.id === id)
  if (!term) return
  clearFeedback()
  selectedTermId.value = id
  appStore.setSelectedTerm(id)
  fillTermForm(term)
  resetCourseForm()
  resetOverrideForm()
}

function startNewTerm() {
  clearFeedback()
  selectedTermId.value = ''
  appStore.setSelectedTerm(null)
  Object.assign(termForm, { name: '', label: '', startDate: todayISO(), weeksTotal: 20 })
}

async function makeCurrent(term: TermRow) {
  clearFeedback()
  for (const item of terms.value) {
    if (item.id === term.id && item.is_current === 1 && !item.archived_at) continue
    if (item.is_current === 1 || item.id === term.id) {
      await sync.localWrite('term', item.id, { is_current: item.id === term.id ? 1 : 0, archived_at: item.id === term.id ? null : item.archived_at }, item._rev)
    }
  }
  await load()
  selectedTermId.value = term.id
  appStore.setSelectedTerm(term.id)
  message.value = `已切换到「${term.name}」`
}

async function saveTerm() {
  clearFeedback()
  const name = termForm.name.trim()
  if (!name || !termForm.startDate || termForm.weeksTotal < 1) {
    error.value = '请填写学期名称、第一周周一和正数周数'
    return
  }
  const existing = activeTerm.value
  if (existing) {
    await sync.localWrite(
      'term',
      existing.id,
      { name, label: termForm.label.trim() || null, start_date: termForm.startDate, weeks_total: termForm.weeksTotal },
      existing._rev,
    )
    message.value = '学期设置已保存'
  } else {
    const id = crypto.randomUUID()
    const shouldCurrent = terms.value.length === 0
    if (shouldCurrent) {
      for (const item of terms.value.filter((item) => item.is_current === 1)) {
        await sync.localWrite('term', item.id, { is_current: 0 }, item._rev)
      }
    }
    await sync.localWrite(
      'term',
      id,
      {
        name,
        label: termForm.label.trim() || null,
        start_date: termForm.startDate,
        weeks_total: termForm.weeksTotal,
        is_current: shouldCurrent ? 1 : 0,
        archived_at: null,
      },
      0,
    )
    selectedTermId.value = id
    appStore.setSelectedTerm(id)
    message.value = '新学期已创建'
  }
  await load()
}

async function archiveCurrentTerm() {
  const term = activeTerm.value
  if (!term) return
  const fallback = terms.value.find((item) => item.id !== term.id && !item.archived_at && !item._deleted_at)
  if (!fallback) {
    error.value = '请先新建另一个学期，再归档当前学期'
    return
  }
  clearFeedback()
  await sync.localWrite('term', term.id, { is_current: 0, archived_at: new Date().toISOString() }, term._rev)
  await sync.localWrite('term', fallback.id, { is_current: 1, archived_at: null }, fallback._rev)
  await load()
  selectedTermId.value = fallback.id
  appStore.setSelectedTerm(fallback.id)
  message.value = `已归档「${term.name}」，当前学期切换为「${fallback.name}」`
}

function resetCourseForm() {
  editingCourseId.value = null
  courseEditorOpen.value = false
  Object.assign(courseForm, { name: '', shortName: '', teacher: '', code: '', color: 0, credit: '' })
}

function openCourseCreate() {
  resetCourseForm()
  courseEditorOpen.value = true
}

function editCourse(course: CourseRow) {
  clearFeedback()
  editingCourseId.value = course.id
  Object.assign(courseForm, {
    name: course.name,
    shortName: course.short_name ?? '',
    teacher: course.teacher ?? '',
    code: course.code ?? '',
    color: course.color,
    credit: course.credit == null ? '' : String(course.credit),
  })
  courseEditorOpen.value = true
}

async function saveCourse() {
  clearFeedback()
  const term = activeTerm.value
  const name = courseForm.name.trim()
  if (!term || !name) {
    error.value = '请先选择学期并填写课程名'
    return
  }
  const credit = courseForm.credit.trim() ? Number(courseForm.credit) : null
  if (credit !== null && !Number.isFinite(credit)) {
    error.value = '学分必须是数字'
    return
  }
  const fields = {
    name,
    short_name: courseForm.shortName.trim() || null,
    teacher: courseForm.teacher.trim() || null,
    code: courseForm.code.trim() || null,
    color: courseForm.color,
    credit,
  }
  const existing = editingCourseId.value ? courses.value.find((item) => item.id === editingCourseId.value) : null
  if (existing) {
    await sync.localWrite('course', existing.id, fields, existing._rev)
    message.value = '课程资料已保存'
  } else {
    await sync.localWrite(
      'course',
      crypto.randomUUID(),
      { ...fields, term_id: term.id, sort_order: activeCourses.value.length },
      0,
    )
    message.value = '课程已创建，可再到课表页添加上课安排'
  }
  resetCourseForm()
  await load()
}

async function archiveCourse(course: CourseRow) {
  if (!window.confirm(`确认归档「${course.name}」吗？它的课程格也会隐藏，但同步墓碑仍会保留。`)) return
  clearFeedback()
  await sync.localWrite('course', course.id, {}, course._rev, true)
  for (const slot of activeSlots.value.filter((item) => item.course_id === course.id)) {
    await sync.localWrite('course_slot', slot.id, {}, slot._rev, true)
  }
  await load()
  message.value = '课程已归档'
}

function resetOverrideForm() {
  editingOverrideId.value = null
  Object.assign(overrideForm, {
    slotId: slotOptions.value[0]?.id ?? '',
    day: todayISO(),
    action: 'room',
    room: '',
    toWeekday: 1,
    toStartLesson: 1,
    toEndLesson: 2,
    note: '',
  })
}

function editOverride(item: TimetableOverrideRow) {
  clearFeedback()
  editingOverrideId.value = item.id
  Object.assign(overrideForm, {
    slotId: item.slot_id ?? '',
    day: item.day,
    action: item.action,
    room: item.room ?? '',
    toWeekday: item.to_weekday ?? 1,
    toStartLesson: item.to_start_lesson ?? 1,
    toEndLesson: item.to_end_lesson ?? 2,
    note: item.note ?? '',
  })
}

async function saveOverride() {
  clearFeedback()
  const term = activeTerm.value
  const slot = slotOptions.value.find((item) => item.id === overrideForm.slotId)
  if (!term || !slot || !/^\d{4}-\d{2}-\d{2}$/.test(overrideForm.day)) {
    error.value = '请选择课程安排并填写有效日期'
    return
  }
  if (overrideForm.action === 'room' && !overrideForm.room.trim()) {
    error.value = '换教室需要填写新教室'
    return
  }
  if (overrideForm.action === 'move' && overrideForm.toEndLesson < overrideForm.toStartLesson) {
    error.value = '调课结束小节不能早于开始小节'
    return
  }
  const fields = {
    term_id: term.id,
    day: overrideForm.day,
    action: overrideForm.action,
    course_id: slot.course_id,
    slot_id: slot.id,
    to_weekday: overrideForm.action === 'move' ? overrideForm.toWeekday : null,
    to_start_lesson: overrideForm.action === 'move' ? overrideForm.toStartLesson : null,
    to_end_lesson: overrideForm.action === 'move' ? overrideForm.toEndLesson : null,
    room: overrideForm.action === 'room' ? overrideForm.room.trim() : null,
    note: overrideForm.note.trim() || null,
  }
  const existing = editingOverrideId.value
    ? overrides.value.find((item) => item.id === editingOverrideId.value)
    : null
  if (existing) {
    await sync.localWrite('timetable_override', existing.id, fields, existing._rev)
    message.value = '单次覆盖已更新'
  } else {
    await sync.localWrite('timetable_override', crypto.randomUUID(), fields, 0)
    message.value = '单次覆盖已保存'
  }
  resetOverrideForm()
  await load()
}

async function removeOverride(item: TimetableOverrideRow) {
  if (!window.confirm(`删除 ${item.day} 的单次覆盖吗？`)) return
  await sync.localWrite('timetable_override', item.id, {}, item._rev, true)
  await load()
  message.value = '单次覆盖已删除'
}

function courseName(courseId: string | null): string {
  return courses.value.find((course) => course.id === courseId)?.name ?? '未知课程'
}

function actionLabel(action: string): string {
  return action === 'cancel' ? '停课' : action === 'move' ? '调课' : '换教室'
}

async function exportBackup() {
  backupBusy.value = true
  backupMessage.value = ''
  try {
    const blob = await createLocalBackup()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `supercourse-backup-${todayISO()}.json`
    link.click()
    URL.revokeObjectURL(url)
    backupMessage.value = '本地备份已下载'
  } catch {
    backupMessage.value = '备份失败，请稍后重试'
  } finally {
    backupBusy.value = false
  }
}

async function importBackup(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!window.confirm('导入备份会合并同 ID 数据，确认继续吗？')) return
  backupBusy.value = true
  backupMessage.value = ''
  try {
    const counts = await restoreLocalBackup(file)
    await load()
    backupMessage.value = `备份已导入，共恢复 ${Object.values(counts).reduce((sum, count) => sum + count, 0)} 条数据`
  } catch (cause) {
    backupMessage.value = cause instanceof Error ? cause.message : '备份导入失败'
  } finally {
    backupBusy.value = false
  }
}
</script>

<template>
  <section class="manage">
    <header class="view-head">
      <div>
        <h1>管理</h1>
        <p>学期、课程资料和单次课表变化</p>
      </div>
      <RouterLink
        v-if="!isLocalMode()"
        class="ghost-btn"
        to="/import"
      >导入课表</RouterLink>
    </header>

    <p
      v-if="message"
      class="feedback success"
    >{{ message }}</p>
    <p
      v-if="error"
      class="feedback error"
    >{{ error }}</p>

    <div
      v-if="!loaded"
      class="state-pill"
    >正在加载管理数据…</div>
    <template v-else>
      <section class="panel">
        <div class="section-head">
          <div>
            <h2>学期</h2>
            <p class="muted">已归档学期保留查看，不再作为当前课表。</p>
          </div>
          <button
            class="ghost-btn"
            type="button"
            @click="startNewTerm"
          >+ 新建学期</button>
        </div>
        <div
          v-if="terms.length"
          class="term-list"
        >
          <button
            v-for="item in terms"
            :key="item.id"
            type="button"
            class="term-item"
            :class="{ selected: item.id === selectedTermId }"
            @click="selectTerm(item.id)"
          >
            <span>
              <strong>{{ item.name }}</strong>
              <small>{{ item.start_date }} · {{ item.weeks_total }} 周</small>
            </span>
            <span class="term-state">{{ item.is_current ? '当前' : item.archived_at ? '已归档' : '可切换' }}</span>
          </button>
        </div>
        <p
          v-else
          class="empty"
        >还没有学期，先新建一个。</p>
        <form
          class="form-grid"
          @submit.prevent="saveTerm"
        >
          <label>
            <span>学期名称</span>
            <input
              v-model="termForm.name"
              placeholder="如 2026-2027-1"
              required
            >
          </label>
          <label>
            <span>显示标签（可选）</span>
            <input
              v-model="termForm.label"
              placeholder="秋季学期"
            >
          </label>
          <label>
            <span>第一周周一</span>
            <input
              v-model="termForm.startDate"
              type="date"
              required
            >
          </label>
          <label>
            <span>总周数</span>
            <input
              v-model.number="termForm.weeksTotal"
              min="1"
              max="60"
              type="number"
            >
          </label>
          <div class="form-actions">
            <button
              class="primary-btn"
              type="submit"
            >保存学期</button>
            <button
              v-if="activeTerm && !activeTerm.archived_at"
              class="danger-btn"
              type="button"
              @click="archiveCurrentTerm"
            >归档当前学期</button>
            <button
              v-if="activeTerm && (activeTerm.archived_at || !activeTerm.is_current)"
              class="ghost-btn"
              type="button"
              @click="makeCurrent(activeTerm)"
            >设为当前</button>
          </div>
        </form>
      </section>

      <section class="panel">
        <div class="section-head">
          <div>
            <h2>课程资料</h2>
            <p class="muted">课程格里的内容和颜色会立即跟着这里更新。</p>
          </div>
          <button
            class="ghost-btn"
            type="button"
            @click="openCourseCreate"
          >+ 新建课程</button>
        </div>
        <div
          v-if="activeCourses.length"
          class="course-list"
        >
          <article
            v-for="course in activeCourses"
            :key="course.id"
            class="course-row"
          >
            <span
              class="color-dot"
              :style="{ background: PALETTE[course.color % PALETTE.length] }"
            />
            <RouterLink
              class="course-info"
              :to="`/courses/${course.id}`"
            >
              <strong>{{ course.name }}</strong>
              <small>{{ [course.teacher, course.code].filter(Boolean).join(' · ') || '暂无教师/课程代码' }}</small>
            </RouterLink>
            <button
              class="ghost-btn"
              type="button"
              @click="editCourse(course)"
            >编辑</button>
            <button
              class="ghost-btn danger"
              type="button"
              @click="archiveCourse(course)"
            >归档</button>
          </article>
        </div>
        <p
          v-else
          class="empty"
        >当前学期还没有课程资料。</p>
        <div
          v-if="courseEditorOpen"
          class="dialog-backdrop"
          @click.self="resetCourseForm"
        >
          <form
            class="course-dialog"
            @submit.prevent="saveCourse"
          >
            <div class="dialog-head">
              <h3>{{ editingCourseId ? '编辑课程' : '新建课程' }}</h3>
              <button class="close-btn" type="button" aria-label="关闭" @click="resetCourseForm">×</button>
            </div>
          <label>
            <span>课程名</span>
            <input
              v-model="courseForm.name"
              required
            >
          </label>
          <label>
            <span>简称</span>
            <input v-model="courseForm.shortName">
          </label>
          <label>
            <span>教师</span>
            <input v-model="courseForm.teacher">
          </label>
          <label>
            <span>课程代码</span>
            <input v-model="courseForm.code">
          </label>
          <label>
            <span>学分</span>
            <input
              v-model="courseForm.credit"
              inputmode="decimal"
            >
          </label>
          <label>
            <span>课程颜色</span>
            <select v-model.number="courseForm.color">
              <option
                v-for="(color, index) in PALETTE"
                :key="color"
                :value="index"
              >颜色 {{ index + 1 }}</option>
            </select>
          </label>
            <div class="form-actions">
            <button
              class="primary-btn"
              type="submit"
            >{{ editingCourseId ? '保存课程' : '创建课程' }}</button>
            <button
              v-if="editingCourseId"
              class="ghost-btn"
              type="button"
              @click="resetCourseForm"
            >取消编辑</button>
            </div>
          </form>
        </div>
      </section>

      <section class="panel">
        <div class="section-head">
          <div>
            <h2>单次覆盖</h2>
            <p class="muted">只影响某个日期，不修改固定课表；可用于停课、换教室或调课。</p>
          </div>
          <button
            class="ghost-btn"
            type="button"
            @click="resetOverrideForm"
          >+ 新建覆盖</button>
        </div>
        <div
          v-if="activeOverrides.length"
          class="override-list"
        >
          <article
            v-for="item in activeOverrides"
            :key="item.id"
            class="override-row"
          >
            <div>
              <strong>{{ item.day }} · {{ courseName(item.course_id) }}</strong>
              <small>{{ actionLabel(item.action) }}{{ item.room ? ` → ${item.room}` : '' }}{{ item.note ? ` · ${item.note}` : '' }}</small>
            </div>
            <div class="row-actions">
              <button
                class="ghost-btn"
                type="button"
                @click="editOverride(item)"
              >编辑</button>
              <button
                class="ghost-btn danger"
                type="button"
                @click="removeOverride(item)"
              >删除</button>
            </div>
          </article>
        </div>
        <p
          v-else
          class="empty"
        >当前学期还没有单次覆盖。</p>
        <form
          class="form-grid override-form"
          @submit.prevent="saveOverride"
        >
          <label class="wide">
            <span>固定课程格</span>
            <select v-model="overrideForm.slotId">
              <option
                v-for="slot in slotOptions"
                :key="slot.id"
                :value="slot.id"
              >{{ slot.label }}</option>
            </select>
          </label>
          <label>
            <span>日期</span>
            <input
              v-model="overrideForm.day"
              type="date"
              required
            >
          </label>
          <label>
            <span>类型</span>
            <select v-model="overrideForm.action">
              <option value="room">换教室</option>
              <option value="cancel">停课</option>
              <option value="move">调课</option>
            </select>
          </label>
          <label v-if="overrideForm.action === 'room'">
            <span>新教室</span>
            <input v-model="overrideForm.room">
          </label>
          <template v-if="overrideForm.action === 'move'">
            <label>
              <span>目标星期</span>
              <select v-model.number="overrideForm.toWeekday">
                <option
                  v-for="day in 7"
                  :key="day"
                  :value="day"
                >周{{ DAY_NAMES[day - 1] }}</option>
              </select>
            </label>
            <label>
              <span>目标开始节</span>
              <input
                v-model.number="overrideForm.toStartLesson"
                min="1"
                max="12"
                type="number"
              >
            </label>
            <label>
              <span>目标结束节</span>
              <input
                v-model.number="overrideForm.toEndLesson"
                min="1"
                max="12"
                type="number"
              >
            </label>
          </template>
          <label class="wide">
            <span>说明（可选）</span>
            <input
              v-model="overrideForm.note"
              placeholder="如：临时换到实验楼"
            >
          </label>
          <div class="form-actions">
            <button
              class="primary-btn"
              type="submit"
            >{{ editingOverrideId ? '保存覆盖' : '保存覆盖' }}</button>
            <button
              v-if="editingOverrideId"
              class="ghost-btn"
              type="button"
              @click="resetOverrideForm"
            >取消编辑</button>
          </div>
        </form>
      </section>
      <ReminderSettingsPanel />
      <section class="panel utility-panel">
        <div class="section-head">
          <div>
            <h2>本地备份</h2>
            <p class="muted">导出当前设备上的课程、待办和图片；备份文件只保存在你的设备上。</p>
          </div>
        </div>
        <div class="form-actions">
          <button class="ghost-btn" type="button" :disabled="backupBusy" @click="exportBackup">导出本地备份</button>
          <button class="ghost-btn" type="button" :disabled="backupBusy" @click="backupInput?.click()">导入本地备份</button>
          <input ref="backupInput" class="visually-hidden" type="file" accept="application/json,.json" @change="importBackup">
        </div>
        <p v-if="backupMessage" class="muted">{{ backupMessage }}</p>
      </section>
      <section class="panel utility-panel">
        <div class="section-head">
          <div>
            <h2>同步与问题处理</h2>
            <p class="muted">冲突需要人工选择保留哪一端；诊断页用于确认本地数据和提醒调度状态。</p>
          </div>
        </div>
        <div class="form-actions">
          <RouterLink
            class="ghost-btn"
            to="/conflicts"
          >打开冲突箱</RouterLink>
          <RouterLink
            class="ghost-btn"
            to="/diagnostics"
          >打开诊断页</RouterLink>
          <RouterLink
            class="ghost-btn"
            to="/reminders"
          >查看提醒</RouterLink>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.manage {
  padding-top: 4px;
}
.ghost-btn,
.primary-btn,
.danger-btn {
  min-height: 38px;
  padding: 0 13px;
  border-radius: 8px;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}
.ghost-btn {
  border: 1px solid var(--line-strong);
  background: var(--surface);
  color: var(--text);
}
.primary-btn {
  border: 1px solid var(--accent);
  background: var(--accent);
  color: #fff;
  font-weight: 600;
}
.danger-btn,
.ghost-btn.danger {
  border: 1px solid color-mix(in srgb, var(--danger) 55%, var(--line));
  background: transparent;
  color: var(--danger);
}
.ghost-btn:hover,
.primary-btn:hover,
.danger-btn:hover {
  filter: brightness(0.97);
}
.feedback {
  margin: 14px 0 0;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 13px;
}
.feedback.success {
  color: var(--accent);
  background: var(--accent-soft);
}
.feedback.error {
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 9%, var(--surface));
}
.panel {
  margin-top: 18px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
}
.section-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.section-head h2 {
  margin: 0;
  font-size: 17px;
}
.section-head p {
  margin: 5px 0 0;
}
.muted,
.term-item small,
.course-info small,
.override-row small {
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.55;
}
.term-list,
.course-list,
.override-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 16px;
}
.term-item,
.course-row,
.override-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 54px;
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}
.term-item {
  justify-content: space-between;
  width: 100%;
  text-align: left;
  cursor: pointer;
}
.term-item.selected {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.term-item span:first-child,
.course-info,
.override-row > div:first-child {
  display: grid;
  gap: 2px;
}
.term-state {
  color: var(--accent);
  font-size: 12px;
  white-space: nowrap;
}
.term-item strong,
.course-row strong,
.override-row strong {
  font-size: 14px;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 13px;
  margin-top: 18px;
}
.form-grid label {
  display: grid;
  gap: 5px;
  color: var(--text-secondary);
  font-size: 13px;
}
.form-grid label.wide {
  grid-column: 1 / -1;
}
.form-grid input,
.form-grid select {
  width: 100%;
  min-height: 40px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
}
.form-grid input:focus,
.form-grid select:focus {
  border: 2px solid var(--accent);
  outline: none;
}
.dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 20;
  display: grid;
  place-items: center;
  padding: 18px;
  background: rgb(15 23 42 / 28%);
}
.course-dialog {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 13px;
  width: min(620px, 100%);
  max-height: min(760px, 90vh);
  overflow: auto;
  padding: 20px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: 0 18px 60px rgb(15 23 42 / 20%);
}
.course-dialog label {
  display: grid;
  gap: 5px;
  color: var(--text-secondary);
  font-size: 13px;
}
.course-dialog input,
.course-dialog select {
  width: 100%;
  min-height: 40px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
}
.course-dialog input:focus,
.course-dialog select:focus {
  border: 2px solid var(--accent);
  outline: none;
}
.course-dialog .dialog-head,
.course-dialog .form-actions {
  grid-column: 1 / -1;
}
.dialog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.dialog-head h3 { margin: 0; font-size: 18px; }
.close-btn {
  width: 34px;
  height: 34px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 22px;
  cursor: pointer;
}
.form-actions {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.course-row,
.override-row {
  min-height: 60px;
}
.course-info,
.override-row > div:first-child {
  flex: 1;
  min-width: 0;
}
.color-dot {
  width: 12px;
  height: 34px;
  flex: 0 0 auto;
  border-radius: 5px;
}
.row-actions {
  display: flex;
  gap: 7px;
}
.empty,
.state-pill {
  margin: 16px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  text-align: center;
}
.state-pill {
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
}
@media (max-width: 620px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
  .course-dialog {
    grid-template-columns: 1fr;
  }
  .form-grid label.wide,
  .form-actions {
    grid-column: auto;
  }
  .section-head {
    flex-direction: column;
  }
  .section-head > .ghost-btn {
    align-self: flex-start;
  }
  .course-row,
  .override-row {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .course-info,
  .override-row > div:first-child {
    flex-basis: calc(100% - 24px);
  }
  .course-row > .ghost-btn,
  .row-actions {
    margin-left: 22px;
  }
}
</style>

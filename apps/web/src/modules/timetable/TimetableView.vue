<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import {
  db,
  type CourseRow,
  type CourseSlotRow,
  type LessonPeriodRow,
  type TermRow,
  type TimetableOverrideRow,
} from '../../db/db'
import { sync } from '../../core/sync'
import { isLocalMode } from '../../core/connection'
import { canonicalCourseIds } from '../../core/courses'
import { useAppStore } from '../../stores/app'
import {
  blockRowSpan,
  applyDayOverrides,
  canonicalTermStartDate,
  currentWeek,
  deriveBigPeriodRows,
  mergeConsecutive,
  weekDates,
  weekHeader,
  type BigPeriodRow,
} from './derive'

const appStore = useAppStore()

const term = ref<TermRow | null>(null)
const courses = ref<CourseRow[]>([])
const slots = ref<CourseSlotRow[]>([])
const periods = ref<LessonPeriodRow[]>([])
const overrides = ref<TimetableOverrideRow[]>([])
const week = ref(1)
const loaded = ref(false)
const editorOpen = ref(false)
const editorMode = ref<'new' | 'edit'>('new')
const editorError = ref('')
const editingCourseId = ref('')
const editingSlotId = ref('')
const editorForm = reactive({
  name: '',
  teacher: '',
  weekday: 1,
  startLesson: 1,
  endLesson: 2,
  room: '',
  weeksText: '1-20',
})

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

onMounted(async () => {
  await load()
  // 同步完成后重新读库（sync 拉取是异步的，可能晚于组件挂载）。
  sync.subscribe((s) => {
    if (s.lastSyncAt) {
      void load()
    }
  })
})

async function load() {
  const terms = (await db.term.toArray()).filter((item) => !item._deleted_at)
  term.value = terms.find((t) => t.id === appStore.selectedTermId) ?? terms.find((t) => t.is_current === 1) ?? terms[0] ?? null
  if (term.value) {
    const startDate = canonicalTermStartDate(term.value)
    if (startDate !== term.value.start_date) {
      const oldTerm = term.value
      await sync.localWrite('term', oldTerm.id, { start_date: startDate }, oldTerm._rev)
      term.value = { ...oldTerm, start_date: startDate }
    }
  }
  courses.value = await db.course.toArray()
  slots.value = await db.course_slot.toArray()
  periods.value = await db.lesson_period.toArray()
  overrides.value = await db.timetable_override.toArray()
  if (term.value) {
    week.value = currentWeek(term.value.start_date, todayISO(), term.value.weeks_total)
  }
  loaded.value = true
}

const today = ref(todayISO())

function todayISO(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const activeTermId = computed(() => term.value?.id ?? '')
const activeCoursePool = computed(() =>
  courses.value.filter((course) => course.term_id === activeTermId.value && !course._deleted_at),
)
const canonicalCourseIdMap = computed(() => canonicalCourseIds(activeCoursePool.value))

const courseMap = computed(() => {
  const m = new Map<string, CourseRow>()
  courses.value.forEach((course) => {
    const canonicalId = canonicalCourseIdMap.value.get(course.id)
    const canonical = canonicalId ? activeCoursePool.value.find((item) => item.id === canonicalId) : null
    m.set(course.id, canonical ?? course)
  })
  return m
})

const readOnly = computed(() => Boolean(term.value?.archived_at))

const validSlots = computed(() => slots.value.filter((s) => s.course_id && !s._deleted_at))

const blocks = computed(() => {
  if (!activeTermId.value) return []
  // 仅取当前 term 的课程对应格（通过 course.term_id 过滤）
  const courseIds = new Set(courses.value.filter((c) => c.term_id === activeTermId.value).map((c) => c.id))
  const visible = validSlots.value
    .filter((s) => courseIds.has(s.course_id))
    .map((slot) => ({
      ...slot,
      course_id: canonicalCourseIdMap.value.get(slot.course_id) ?? slot.course_id,
    }))
  return mergeConsecutive(visible, week.value)
})

/** 把某周的具体日期覆盖应用到固定课表，不修改主课表。 */
const displayBlocks = computed(() => {
  return applyDayOverrides(
    blocks.value,
    header.value,
    overrides.value
      .filter((item) => !item._deleted_at && item.term_id === activeTermId.value)
      .map((item) => ({
        day: item.day,
        action: item.action,
        slotId: item.slot_id,
        courseId: item.course_id,
        room: item.room,
        toWeekday: item.to_weekday,
        toStartLesson: item.to_start_lesson,
        toEndLesson: item.to_end_lesson,
      })),
  )
})

const dateRange = computed(() => {
  if (!term.value) return ''
  const { monday, sunday } = weekDates(term.value.start_date, week.value)
  return `${monday} - ${sunday}`
})

const header = computed(() => weekHeader(term.value?.start_date ?? today.value, week.value))

const weekBlocks = computed(() => displayBlocks.value)

/** 大节行锚点（由作息表推导，不写死大节数）。 */
const bigRows = computed<BigPeriodRow[]>(() => deriveBigPeriodRows(periods.value))

/** 周视图课程块：附加跨大节行区间 + 完整课程名。 */
const weekCourses = computed(() => {
  const rows = bigRows.value
  return weekBlocks.value.map((b) => {
    const span = blockRowSpan(b, rows)
    const course = courseMap.value.get(b.courseId)
    return {
      ...b,
      rowFrom: span.from,
      rowTo: span.to,
      displayName: course?.name ?? courseName(b.courseId),
      color: colorOf(b.courseId),
    }
  })
})

/** 单日视图：固定展示一天的各大节，并明确标出每节是有课还是空闲。 */
const dayRows = computed(() => {
  const weekday = header.value.find((item) => item.date === today.value)?.weekday ?? 1
  return bigRows.value.map((row) => ({
    ...row,
    courses: displayBlocks.value
      .filter((block) => block.weekday === weekday && block.startLesson <= row.lastLesson && block.endLesson >= row.firstLesson)
      .map((block) => {
        const course = courseMap.value.get(block.courseId)
        return {
          ...block,
          displayName: course?.name ?? courseName(block.courseId),
          color: colorOf(block.courseId),
        }
      }),
  }))
})

function colorOf(courseId: string): string {
  const course = courseMap.value.get(courseId)
  return PALETTE[(course?.color ?? 0) % PALETTE.length]
}

function timeRange(start: number, end: number): string {
  const s = periods.value.find((p) => p.lesson_no === start)
  const e = periods.value.find((p) => p.lesson_no === end)
  return s && e ? `${s.start_time}-${e.end_time}` : `第${start}-${end}节`
}

function colorMix(hex: string): string {
  // 淡染模式：8% 颜色混入 surface。
  const [r, g, b] = hex.match(/\w\w/g)!.map((x) => parseInt(x, 16))
  return `rgba(${r}, ${g}, ${b}, 0.09)`
}

function courseName(courseId: string): string {
  const c = courseMap.value.get(courseId)
  return c ? c.name : '未知课程'
}

function defaultWeeksText() {
  return `1-${term.value?.weeks_total ?? 20}`
}

function weeksTextFromJson(raw: string): string {
  try {
    const spec = JSON.parse(raw) as {
      ranges?: number[][]
      only?: number[]
      parity?: string
    }
    const parts = (spec.ranges ?? []).map((range) => `${range[0]}-${range[1]}`)
    parts.push(...(spec.only ?? []).map(String))
    if (spec.parity === 'odd') parts.push('单周')
    if (spec.parity === 'even') parts.push('双周')
    return parts.join(',') || defaultWeeksText()
  } catch {
    return defaultWeeksText()
  }
}

function weeksJsonFromText(raw: string): string | null {
  const input = raw.trim()
  if (!input) return null
  if (input.startsWith('{')) {
    try {
      return JSON.stringify(JSON.parse(input))
    } catch {
      return null
    }
  }
  const parity = /单周|odd/i.test(input) ? 'odd' : /双周|even/i.test(input) ? 'even' : 'all'
  const ranges: number[][] = []
  const only: number[] = []
  const parts = input
    .replace(/单周|双周|odd|even/gi, '')
    .replace(/周/g, '')
    .split(/[,，、\s]+/)
    .filter(Boolean)
  for (const part of parts) {
    const range = part.match(/^(\d+)\s*-\s*(\d+)$/)
    if (range) {
      ranges.push([Math.min(Number(range[1]), Number(range[2])), Math.max(Number(range[1]), Number(range[2]))])
    } else if (/^\d+$/.test(part)) {
      only.push(Number(part))
    } else {
      return null
    }
  }
  if (ranges.length === 0 && only.length === 0) return null
  return JSON.stringify({ ranges, only, except: [], parity })
}

function openNewEditor() {
  if (!term.value || readOnly.value) return
  editorMode.value = 'new'
  editingCourseId.value = ''
  editingSlotId.value = ''
  Object.assign(editorForm, {
    name: '',
    teacher: '',
    weekday: header.value.find((item) => item.date === today.value)?.weekday ?? 1,
    startLesson: 1,
    endLesson: 2,
    room: '',
    weeksText: defaultWeeksText(),
  })
  editorError.value = ''
  editorOpen.value = true
}

function openEditEditor(slotId: string) {
  if (readOnly.value) return
  const slot = slots.value.find((item) => item.id === slotId)
  const course = slot ? courseMap.value.get(slot.course_id) : null
  if (!slot || !course || slot._deleted_at) return
  editorMode.value = 'edit'
  editingCourseId.value = course.id
  editingSlotId.value = slot.id
  Object.assign(editorForm, {
    name: course.name,
    teacher: course.teacher ?? '',
    weekday: slot.weekday,
    startLesson: slot.start_lesson,
    endLesson: slot.end_lesson,
    room: slot.room ?? '',
    weeksText: weeksTextFromJson(slot.weeks),
  })
  editorError.value = ''
  editorOpen.value = true
}

async function saveEditor() {
  if (!term.value || readOnly.value) return
  const name = editorForm.name.trim()
  const weeks = weeksJsonFromText(editorForm.weeksText)
  if (!name) {
    editorError.value = '课程名不能为空'
    return
  }
  if (!weeks) {
    editorError.value = '周次请填写如 1-16、1,3,5 或单周'
    return
  }
  if (editorForm.endLesson < editorForm.startLesson) {
    editorError.value = '结束小节不能早于开始小节'
    return
  }

  const slotSet = {
    weekday: editorForm.weekday,
    start_lesson: editorForm.startLesson,
    end_lesson: editorForm.endLesson,
    room: editorForm.room.trim() || null,
    weeks,
  }
  if (editorMode.value === 'new') {
    const courseId = crypto.randomUUID()
    const slotId = crypto.randomUUID()
    await sync.localWrite(
      'course',
      courseId,
      {
        term_id: term.value.id,
        name,
        short_name: null,
        teacher: editorForm.teacher.trim() || null,
        code: null,
        color: courses.value.length % PALETTE.length,
        sort_order: courses.value.length,
      },
      0,
    )
    await sync.localWrite('course_slot', slotId, { course_id: courseId, ...slotSet }, 0)
  } else {
    const course = courseMap.value.get(editingCourseId.value)
    const slot = slots.value.find((item) => item.id === editingSlotId.value)
    if (!course || !slot) return
    await sync.localWrite(
      'course',
      course.id,
      { name, teacher: editorForm.teacher.trim() || null },
      course._rev,
    )
    await sync.localWrite('course_slot', slot.id, slotSet, slot._rev)
  }
  editorOpen.value = false
  await load()
}

async function deleteEditorSlot() {
  if (editorMode.value !== 'edit' || readOnly.value) return
  const slot = slots.value.find((item) => item.id === editingSlotId.value)
  if (!slot || !window.confirm('确认删除这条课程安排吗？删除后仍可通过同步恢复。')) return
  await sync.localWrite('course_slot', slot.id, {}, slot._rev, true)
  editorOpen.value = false
  await load()
}

</script>

<template>
  <section class="timetable">
    <header class="view-head">
      <div>
        <h1>课表</h1>
        <p v-if="appStore.mobileView === 'day'">{{ today }} · 单日课表</p>
        <p v-else>第 {{ week }} 周 · {{ dateRange }}</p>
      </div>
      <button
        class="add-course-btn"
        type="button"
        :disabled="readOnly"
        @click="openNewEditor"
      >+ 添加课程</button>
      <button
        class="icon-btn"
        :aria-label="appStore.mobileView === 'day' ? '切换周视图' : '切换单日视图'"
        @click="appStore.mobileView = appStore.mobileView === 'day' ? 'week' : 'day'"
      >
        <span class="view-toggler">
          {{ appStore.mobileView === 'day' ? '周' : '日' }}
        </span>
      </button>
    </header>

    <div
      v-if="!loaded"
      class="state-pill"
    >
      正在加载课表…
    </div>
    <div
      v-else-if="!term"
      class="empty-state"
    >
              {{ isLocalMode() ? '还没有课表。请先添加课程，或在管理页导入本地备份。' : '还没有课表。请先登录并同步课表，或点右上角「添加课程」。' }}
    </div>

    <nav
      v-if="loaded && term && appStore.mobileView !== 'day'"
      class="week-ctrl"
      aria-label="周次切换"
    >
      <button
        class="week-btn"
        :disabled="week <= 1"
        aria-label="上一周"
        @click="week > 1 && week--"
      >‹</button>
      <span class="week-label">第 {{ week }} 周</span>
      <button
        class="week-btn"
        :disabled="week >= (term?.weeks_total ?? 20)"
        aria-label="下一周"
        @click="week < (term?.weeks_total ?? 20) && week++"
      >›</button>
    </nav>

    <template v-if="loaded && term">
      <p
        v-if="readOnly"
        class="readonly-note"
      >当前正在查看已归档学期，课表只读。</p>
      <template v-if="appStore.mobileView === 'day'">
        <nav
          class="day-tabs"
          aria-label="星期切换"
        >
          <button
            v-for="h in header"
            :key="h.weekday"
            class="day-tab"
            :class="{ active: h.date === today }"
            :aria-current="h.date === today ? 'date' : undefined"
            @click="today = h.date"
          >
            {{ h.label }}
          </button>
        </nav>
        <div class="day-grid">
          <article
            v-for="row in dayRows"
            :key="row.big"
            class="day-period"
          >
            <div class="day-period-meta">
              <strong>{{ row.big }}大节</strong>
              <span>第{{ row.firstLesson }}-{{ row.lastLesson }}节</span>
              <small>{{ row.start }}-{{ row.end }}</small>
            </div>
            <div class="day-period-content">
              <article
                v-for="course in row.courses"
                :key="`${row.big}-${course.slotId}`"
                class="day-course"
                :style="{ borderLeftColor: course.color, background: colorMix(course.color) }"
                role="button"
                tabindex="0"
                :aria-label="`编辑${course.displayName}`"
                @click="openEditEditor(course.slotId)"
                @keydown.enter="openEditEditor(course.slotId)"
              >
                <strong>{{ course.displayName }}</strong>
                <span>{{ course.room || '未设置教室' }}</span>
                <small>第{{ course.startLesson }}-{{ course.endLesson }}节</small>
              </article>
              <span
                v-if="row.courses.length === 0"
                class="day-free"
              >空闲</span>
            </div>
          </article>
          <div
            v-if="dayRows.length === 0"
            class="empty-state"
          >
            尚未配置作息时间
          </div>
        </div>
      </template>

      <template v-else>
        <!-- 周视图：左侧大节时间轴 + 7 列网格，课程按小节跨行定位 -->
        <div class="week-grid">
          <div class="week-head">
            <span class="week-axis-head">时间</span>
            <span
              v-for="h in header"
              :key="h.weekday"
              class="week-head-cell"
              :class="{ today: h.date === today }"
            >
              <b>周{{ h.label }}</b>
              <small>{{ h.date.slice(5) }}</small>
            </span>
          </div>
          <div
            class="week-body"
            :style="{ gridTemplateRows: `repeat(${bigRows.length}, minmax(72px, 1fr))` }"
          >
            <template
              v-for="(row, rowIndex) in bigRows"
              :key="row.big"
            >
              <div
                class="week-axis"
                :style="{ gridColumn: 1, gridRow: rowIndex + 1 }"
              >
                <span class="axis-time">{{ row.start }}</span>
                <span class="axis-label">{{ row.big }}大节</span>
              </div>
              <span
                v-for="(h, dayIndex) in header"
                :key="`${row.big}-${h.weekday}`"
                class="week-cell"
                :class="{ today: h.date === today }"
                :style="{ gridColumn: dayIndex + 2, gridRow: rowIndex + 1 }"
              />
            </template>
            <!-- 课程块：跨行跨列定位 -->
            <article
              v-for="b in weekCourses"
              :key="'wc-' + b.slotId"
              class="week-course"
              :style="{
                gridColumn: (b.weekday + 1) + ' / span 1',
                gridRow: (b.rowFrom + 1) + ' / ' + (b.rowTo + 2),
                borderLeftColor: b.color,
                background: colorMix(b.color),
              }"
              role="button"
              tabindex="0"
              :aria-label="`编辑${b.displayName}`"
              @click="openEditEditor(b.slotId)"
              @keydown.enter="openEditEditor(b.slotId)"
            >
              <span class="wc-name">{{ b.displayName }}</span>
              <span class="wc-room">{{ b.room || '' }}</span>
              <span class="wc-time">{{ timeRange(b.startLesson, b.endLesson) }}</span>
            </article>
          </div>
        </div>
      </template>
    </template>

    <div
      v-if="editorOpen"
      class="editor-backdrop"
      @click.self="editorOpen = false"
    >
      <section
        class="editor-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="course-editor-title"
      >
        <div class="editor-head">
          <div>
            <h2 id="course-editor-title">{{ editorMode === 'new' ? '添加课程' : '编辑课程' }}</h2>
            <p class="muted">保存后先更新本地课表，再自动排队同步。</p>
          </div>
          <button
            class="editor-close"
            type="button"
            aria-label="关闭编辑器"
            @click="editorOpen = false"
          >×</button>
        </div>
        <form
          class="editor-form"
          @submit.prevent="saveEditor"
        >
          <label>
            <span>课程名</span>
            <input
              v-model="editorForm.name"
              required
              autocomplete="off"
            >
          </label>
          <label>
            <span>教师（可选）</span>
            <input
              v-model="editorForm.teacher"
              autocomplete="off"
            >
          </label>
          <div class="editor-row">
            <label>
              <span>星期</span>
              <select v-model.number="editorForm.weekday">
                <option
                  v-for="day in 7"
                  :key="day"
                  :value="day"
                >周{{ ['一', '二', '三', '四', '五', '六', '日'][day - 1] }}</option>
              </select>
            </label>
            <label>
              <span>开始小节</span>
              <input
                v-model.number="editorForm.startLesson"
                min="1"
                max="12"
                type="number"
              >
            </label>
            <label>
              <span>结束小节</span>
              <input
                v-model.number="editorForm.endLesson"
                min="1"
                max="12"
                type="number"
              >
            </label>
          </div>
          <label>
            <span>教室（可选）</span>
            <input
              v-model="editorForm.room"
              autocomplete="off"
            >
          </label>
          <label>
            <span>周次</span>
            <input
              v-model="editorForm.weeksText"
              placeholder="如 1-16、1,3,5、单周"
              autocomplete="off"
            >
          </label>
          <p
            v-if="editorError"
            class="editor-error"
            aria-live="polite"
          >{{ editorError }}</p>
          <div class="editor-actions">
            <button
              v-if="editorMode === 'edit'"
              class="danger-btn"
              type="button"
              @click="deleteEditorSlot"
            >删除安排</button>
            <span class="editor-spacer" />
            <button
              class="ghost-btn"
              type="button"
              @click="editorOpen = false"
            >取消</button>
            <button
              class="primary-btn"
              type="submit"
            >保存</button>
          </div>
        </form>
      </section>
    </div>
  </section>
</template>

<style scoped>
.timetable {
  padding-top: 4px;
}

.add-course-btn {
  min-height: 36px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--accent);
  font-weight: 600;
}
.add-course-btn:hover {
  border-color: var(--accent);
}
.add-course-btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.readonly-note {
  margin: 14px 0 0;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--text-secondary);
  background: var(--surface);
  font-size: 13px;
}

.week-ctrl {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.week-btn {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
  font-size: 18px;
}
.week-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.week-label {
  font-weight: 600;
  color: var(--text);
}

.view-toggler {
  font-weight: 700;
}

.week-grid {
  margin-top: 18px;
  display: grid;
  grid-template-columns: 64px repeat(7, 1fr);
  grid-template-rows: auto auto;
  gap: 6px;
}
.week-head {
  display: grid;
  grid-column: 1 / -1;
  grid-template-columns: 64px repeat(7, 1fr);
  gap: 6px;
}
.week-axis-head {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: var(--text-secondary);
}
.week-head-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 6px 0;
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 12px;
}
.week-head-cell.today b {
  color: var(--accent);
}
.week-body {
  position: relative;
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: 64px repeat(7, 1fr);
  min-height: 400px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
}
.week-axis {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: flex-start;
  gap: 2px;
  padding: 10px 8px;
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: var(--surface);
  font-variant-numeric: tabular-nums;
}
.week-cell {
  min-width: 0;
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.week-cell.today {
  background: color-mix(in srgb, var(--accent) 4%, var(--surface));
}
.axis-time {
  font-size: 13px;
  color: var(--text);
  font-weight: 600;
}
.axis-label {
  font-size: 11px;
  color: var(--text-secondary);
}
.week-course {
  height: calc(100% - 12px);
  align-self: start;
  margin: 6px;
  border-radius: var(--radius);
  padding: 8px;
  border: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 11px;
  overflow: hidden;
  z-index: 2;
  cursor: pointer;
}
.week-course:hover,
.day-course:hover {
  border-color: var(--accent);
}
.wc-name {
  font-weight: 700;
  color: var(--text);
  overflow-wrap: anywhere;
  line-height: 1.35;
}
.wc-room,
.wc-time {
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

.day-grid {
  margin-top: 18px;
  display: grid;
  gap: 10px;
}
.day-period {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  min-height: 92px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--surface);
}
.day-period-meta {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  padding: 12px;
  border-right: 1px solid var(--line);
  background: color-mix(in srgb, var(--accent) 3%, var(--surface));
}
.day-period-meta strong { color: var(--text); }
.day-period-meta span,
.day-period-meta small { color: var(--text-secondary); font-size: 12px; }
.day-period-content {
  display: flex;
  align-items: stretch;
  gap: 8px;
  padding: 8px;
}
.day-course {
  min-width: 150px;
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-left: 3px solid;
  border-radius: 8px;
  color: var(--text);
  cursor: pointer;
}
.day-course span,
.day-course small { color: var(--text-secondary); font-size: 12px; }
.day-free {
  align-self: center;
  padding-left: 4px;
  color: var(--text-secondary);
  font-size: 13px;
}

.empty-state {
  padding: 32px 0;
  text-align: center;
  color: var(--text-secondary);
  font-size: 14px;
}

.state-pill {
  margin-top: 20px;
  padding: 14px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 14px;
  border-radius: var(--radius);
  background: var(--surface);
  border: 1px solid var(--line);
}

.editor-backdrop {
  position: fixed;
  z-index: 20;
  inset: 0;
  display: grid;
  padding: 20px;
  place-items: center;
  background: rgba(32, 33, 31, 0.3);
}
.editor-dialog {
  width: min(520px, 100%);
  max-height: min(720px, 100%);
  overflow: auto;
  padding: 20px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  box-shadow: var(--shadow);
}
.editor-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.editor-head p {
  margin: 4px 0 0;
}
.editor-close {
  width: 36px;
  height: 36px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 22px;
}
.editor-form {
  display: grid;
  gap: 13px;
  margin-top: 18px;
}
.editor-form label {
  display: grid;
  gap: 5px;
  color: var(--text-secondary);
  font-size: 13px;
}
.editor-form input,
.editor-form select {
  width: 100%;
  min-height: 40px;
  box-sizing: border-box;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
}
.editor-form input:focus,
.editor-form select:focus {
  border: 2px solid var(--accent);
  outline: none;
}
.editor-row {
  display: grid;
  grid-template-columns: 1.1fr 1fr 1fr;
  gap: 10px;
}
.editor-error {
  margin: 0;
  color: var(--danger);
  font-size: 13px;
}
.editor-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.editor-actions .primary-btn,
.editor-actions .ghost-btn,
.danger-btn {
  min-height: 40px;
  margin: 0;
  padding: 0 14px;
  border-radius: 8px;
  font-weight: 600;
}
.editor-spacer {
  flex: 1;
}
.danger-btn {
  border: 1px solid color-mix(in srgb, var(--danger) 55%, var(--line));
  background: transparent;
  color: var(--danger);
}
@media (max-width: 560px) {
  .editor-row {
    grid-template-columns: 1fr 1fr;
  }
  .editor-row label:first-child {
    grid-column: 1 / -1;
  }
  .day-period {
    grid-template-columns: 86px minmax(0, 1fr);
  }
  .day-course {
    min-width: 124px;
  }
}
</style>

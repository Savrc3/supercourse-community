<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { db, type CourseRow, type TodoRow } from '../../db/db'
import { sync } from '../../core/sync'
import { decodeTags, formatDue, isDoneStatus, sortTodos } from '../todo/derive'

const todos = ref<TodoRow[]>([])
const courses = ref<CourseRow[]>([])
const loaded = ref(false)
const courseFilter = ref('')
const tagFilter = ref('')

const courseNames = computed(() => new Map(courses.value.map((course) => [course.id, course.name])))
const examCourses = computed(() => courses.value.filter((course) => course.exam_at && !course._deleted_at && (!courseFilter.value || course.id === courseFilter.value)).sort((a, b) => (a.exam_at ?? '').localeCompare(b.exam_at ?? '')))
const groups = computed(() => {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const tomorrow = new Date(today)
  tomorrow.setDate(today.getDate() + 1)
  const endWeek = new Date(today)
  endWeek.setDate(today.getDate() + (7 - (today.getDay() || 7)))
  const result = new Map<string, TodoRow[]>()
  const labels = ['逾期', '今天', '明天', '本周', '以后', '无时间']
  labels.forEach((label) => result.set(label, []))
  sortTodos(todos.value.filter((todo) => !todo._deleted_at && !isDoneStatus(todo.status) && (!courseFilter.value || todo.course_id === courseFilter.value) && (!tagFilter.value || decodeTags(todo.tags).includes(tagFilter.value)))).forEach((todo) => {
    if (!todo.due_at) return result.get('无时间')!.push(todo)
    const due = new Date(todo.due_at.length === 10 ? `${todo.due_at}T23:59:59` : todo.due_at)
    const day = new Date(due)
    day.setHours(0, 0, 0, 0)
    const group = due < today ? '逾期' : day.getTime() === today.getTime() ? '今天' : day.getTime() === tomorrow.getTime() ? '明天' : day <= endWeek ? '本周' : '以后'
    result.get(group)!.push(todo)
  })
  return [...result].filter(([, items]) => items.length)
})

async function load() {
  todos.value = await db.todo.toArray()
  courses.value = await db.course.toArray()
  loaded.value = true
}

let unsubscribe: (() => void) | null = null
onMounted(async () => {
  unsubscribe = sync.subscribe(() => void load())
  await load()
})
onUnmounted(() => unsubscribe?.())
</script>

<template>
  <section class="timeline-view">
    <header class="view-head"><div><h1>时间线</h1><p>按截止时间查看接下来要处理的事情。</p></div><RouterLink
      class="reminder-link"
      to="/reminders"
    >提醒展示</RouterLink></header>
    <div class="filters">
      <label class="filter"><span>课程筛选</span><select v-model="courseFilter"><option value="">全部课程</option><option
        v-for="course in courses"
        :key="course.id"
        :value="course.id"
      >{{ course.name }}</option></select></label>
      <label class="filter"><span>标签筛选</span><input
        v-model="tagFilter"
        placeholder="如 作业"
      ></label>
    </div>
    <p
      v-if="!loaded"
      class="state"
    >正在读取时间线…</p>
    <div
      v-else-if="!groups.length"
      class="state"
    >暂无未完成待办。</div>
    <section
      v-for="([label, items]) in groups"
      :key="label"
      class="timeline-group"
    ><h2>{{ label }} <small>{{ items.length }}</small></h2><template v-if="items.length"><RouterLink
      v-for="todo in items"
      :key="todo.id"
      class="timeline-row"
      :to="`/todo/${todo.id}`"
    ><div><strong>{{ todo.title }}</strong><small>{{ todo.course_id ? courseNames.get(todo.course_id) : '杂事' }}</small></div><span>{{ formatDue(todo) }}</span></RouterLink></template><p v-else class="empty-group">暂无待办</p></section>
    <section
      v-if="examCourses.length"
      class="timeline-group"
    ><h2>考试 <small>{{ examCourses.length }}</small></h2><div
      v-for="course in examCourses"
      :key="course.id"
      class="timeline-row exam-row"
    ><div><strong>{{ course.name }}</strong><small>{{ course.exam_room || '考试地点未填写' }}</small></div><span>{{ course.exam_at }}</span></div></section>
  </section>
</template>

<style scoped>
.empty-group { margin: 0; padding: 12px 13px; border: 1px dashed var(--line); border-radius: 9px; color: var(--text-secondary); font-size: 12px; }
.timeline-view { padding-top: 4px; }.reminder-link { color: var(--accent); font-size: 13px; }.filters { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 18px; }.filter { display: flex; align-items: center; gap: 10px; color: var(--text-secondary); font-size: 13px; }.filter select, .filter input { min-height: 36px; padding: 0 9px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; }.state { margin-top: 22px; padding: 28px; border: 1px solid var(--line); border-radius: var(--radius); color: var(--text-secondary); text-align: center; }.timeline-group { margin-top: 22px; }.timeline-group h2 { margin: 0 0 9px; font-size: 17px; }.timeline-group h2 small { color: var(--text-secondary); font-size: 12px; font-weight: 400; }.timeline-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 13px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); }.timeline-row + .timeline-row { margin-top: 7px; }.timeline-row div { display: grid; gap: 3px; min-width: 0; }.timeline-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }.timeline-row small, .timeline-row > span { color: var(--text-secondary); font-size: 12px; }.timeline-row > span { white-space: nowrap; }
</style>

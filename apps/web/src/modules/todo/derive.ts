import type { TodoRow, TodoStatus } from '../../db/db'

/** 新状态只有 0=未完成、1=已完成；历史四状态仅用于兼容读取。 */
export function isDoneStatus(status: TodoStatus | string): boolean {
  return status === '1' || status === 'done' || status === 'canceled'
}

export const PRIORITY_LABELS: Record<number, string> = {
  0: '低优先级',
  1: '普通优先级',
  2: '高优先级',
}

/** 将本地标签输入转换成去重后的服务端 JSON 字符串。 */
export function encodeTags(input: string): string {
  const tags = [...new Set(input.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean))]
  return JSON.stringify(tags)
}

/** 容错读取历史或手工修改过的标签字段。 */
export function decodeTags(raw: string | null | undefined): string[] {
  if (!raw) return []
  try {
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((tag): tag is string => typeof tag === 'string') : []
  } catch {
    return raw.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean)
  }
}

/** 截止时间排序：有时间优先，时间相同再按优先级、手动顺序和创建时间。 */
export function sortTodos(todos: TodoRow[]): TodoRow[] {
  return [...todos].sort((a, b) => {
    const dueCompare = dueSortKey(a).localeCompare(dueSortKey(b))
    if (dueCompare !== 0) return dueCompare
    return b.priority - a.priority || a.sort_order - b.sort_order || a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id)
  })
}

export function formatDue(todo: Pick<TodoRow, 'due_at' | 'due_all_day'>): string {
  if (!todo.due_at) return '未设置截止时间'
  const date = todo.due_at.slice(0, 10)
  const parts = date.split('-').map(Number)
  if (parts.length !== 3 || parts.some((part) => !Number.isFinite(part))) return `截止 ${todo.due_at}`
  const dateLabel = `${parts[1]}月${parts[2]}日`
  if (todo.due_all_day === 1 || !todo.due_at.includes('T')) return `${dateLabel} · 全天`
  return `${dateLabel} ${todo.due_at.slice(11, 16)}`
}

export function isOverdue(todo: Pick<TodoRow, 'due_at' | 'due_all_day' | 'status'>, now = new Date()): boolean {
  if (!todo.due_at || isDoneStatus(todo.status)) return false
  const due = todo.due_all_day === 1
    ? new Date(`${todo.due_at.slice(0, 10)}T23:59:59`)
    : new Date(todo.due_at.length === 16 ? `${todo.due_at}:00` : todo.due_at)
  return !Number.isNaN(due.getTime()) && due.getTime() < now.getTime()
}

function dueSortKey(todo: Pick<TodoRow, 'due_at'>): string {
  return todo.due_at ?? '\uffff'
}

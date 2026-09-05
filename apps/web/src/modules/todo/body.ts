import type { JSONContent } from '@tiptap/core'

export const EMPTY_TODO_DOC: JSONContent = {
  type: 'doc',
  content: [{ type: 'paragraph' }],
}

/** 从本地/服务端字段读取 Tiptap JSON，旧数据或损坏数据回退为空文档。 */
export function parseTodoBody(raw: string | null | undefined): JSONContent {
  if (!raw) return EMPTY_TODO_DOC
  try {
    const parsed: unknown = JSON.parse(raw)
    if (
      parsed &&
      typeof parsed === 'object' &&
      (parsed as { type?: unknown }).type === 'doc'
    ) {
      return sanitizeTodoBody(parsed as JSONContent)
    }
  } catch {
    // 旧版本可能保存空对象或非 JSON 内容，统一按空正文处理。
  }
  return EMPTY_TODO_DOC
}

/** 只保留编辑器可用节点，并清理危险链接协议。 */
export function sanitizeTodoBody(doc: JSONContent): JSONContent {
  const next: JSONContent = { ...doc }
  if (next.marks) {
    next.marks = next.marks.map((mark) => {
      if (mark.type !== 'link' || typeof mark.attrs?.href !== 'string' || /^https?:\/\//i.test(mark.attrs.href)) return mark
      const { href: _href, ...attrs } = mark.attrs
      return { ...mark, attrs }
    })
  }
  if (next.attrs && typeof next.attrs.href === 'string' && !/^https?:\/\//i.test(next.attrs.href)) {
    const { href: _href, ...attrs } = next.attrs
    next.attrs = attrs
  }
  if (next.attrs && typeof next.attrs.src === 'string' && !/^(media:|https?:\/\/|blob:)/i.test(next.attrs.src)) {
    const { src: _src, ...attrs } = next.attrs
    next.attrs = attrs
  }
  if (next.content) next.content = next.content.map(sanitizeTodoBody)
  return next
}

export function todoBodyText(editorText: string): string {
  return editorText.trim()
}

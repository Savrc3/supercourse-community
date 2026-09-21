import type { JSONContent } from '@tiptap/core'
import { defaultMarkdownParser, defaultMarkdownSerializer, MarkdownParser, MarkdownSerializer } from 'prosemirror-markdown'
import type { Schema } from 'prosemirror-model'

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

const MARKDOWN_NAME_MAP: Record<string, string> = {
  bullet_list: 'bulletList',
  code_block: 'codeBlock',
  hard_break: 'hardBreak',
  hardbreak: 'hardBreak',
  hr: 'horizontalRule',
  horizontal_rule: 'horizontalRule',
  list_item: 'listItem',
  ordered_list: 'orderedList',
  em: 'italic',
  strong: 'bold',
}

const markdownTokens = Object.fromEntries(
  Object.entries(defaultMarkdownParser.tokens).map(([name, spec]) => [
    name,
    {
      ...spec,
      ...(spec.block ? { block: MARKDOWN_NAME_MAP[spec.block] ?? spec.block } : {}),
      ...(spec.node ? { node: MARKDOWN_NAME_MAP[spec.node] ?? spec.node } : {}),
      ...(spec.mark ? { mark: MARKDOWN_NAME_MAP[spec.mark] ?? spec.mark } : {}),
    },
  ]),
)

const markdownNodes = Object.fromEntries(
  Object.entries(defaultMarkdownSerializer.nodes).map(([name, serializer]) => [
    MARKDOWN_NAME_MAP[name] ?? name,
    serializer,
  ]),
)

const markdownMarks = Object.fromEntries(
  Object.entries(defaultMarkdownSerializer.marks).map(([name, serializer]) => [
    MARKDOWN_NAME_MAP[name] ?? name,
    serializer,
  ]),
)

/** 将常用 Markdown 解析为当前 Tiptap schema 可保存的 JSON。 */
export function markdownToTodoBody(markdown: string, schema: Schema): JSONContent {
  const parser = new MarkdownParser(schema, defaultMarkdownParser.tokenizer, markdownTokens)
  return sanitizeTodoBody(promoteTaskLists(parser.parse(markdown).toJSON() as JSONContent))
}

/** 将 Tiptap JSON 转成 Markdown 源码；不保证保留原始排版，只保证语义尽量保留。 */
export function todoBodyToMarkdown(doc: JSONContent, schema: Schema): string {
  const node = schema.nodeFromJSON(sanitizeTodoBody(doc))
  const serializer = new MarkdownSerializer(
    {
      ...markdownNodes,
      bulletList: (state, current) => state.renderList(current, '  ', () => '- '),
      taskList: (state, current) => state.renderList(current, '  ', () => '- '),
      taskItem: (state, current) => {
        state.write(current.attrs?.checked ? '[x] ' : '[ ] ')
        state.renderContent(current)
      },
    },
    markdownMarks,
    { strict: false },
  )
  return serializer.serialize(node, { tightLists: true }).trim()
}

/** CommonMark 本身会把任务清单当普通列表，这里恢复为 Tiptap 的任务清单节点。 */
function promoteTaskLists(node: JSONContent): JSONContent {
  const next: JSONContent = { ...node }
  if (next.content) next.content = next.content.map(promoteTaskLists)
  if (next.type !== 'bulletList' || !next.content?.length) return next

  const taskItems = next.content.map((item) => {
    if (item.type !== 'listItem' || !item.content?.[0] || item.content[0].type !== 'paragraph') return null
    const paragraph = item.content[0]
    const firstText = paragraph.content?.find((child) => child.type === 'text')
    const match = firstText?.text?.match(/^\[([ xX])\]\s?/)
    if (!firstText || !match) return null
    const text = firstText.text?.slice(match[0].length)
    const content = paragraph.content
      ?.map((child) => child === firstText ? { ...child, text } : child)
      .filter((child) => child.type !== 'text' || Boolean(child.text))
    return {
      type: 'taskItem',
      attrs: { checked: match[1].toLowerCase() === 'x' },
      content: [{ ...paragraph, content }, ...item.content.slice(1)],
    }
  })

  return taskItems.every(Boolean) ? { ...next, type: 'taskList', content: taskItems as JSONContent[] } : next
}

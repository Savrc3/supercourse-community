import { describe, expect, it } from 'vitest'
import { getSchema } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'

import { EMPTY_TODO_DOC, markdownToTodoBody, parseTodoBody, sanitizeTodoBody, todoBodyText, todoBodyToMarkdown } from './body'

const schema = getSchema([
  StarterKit,
  Link.configure({ openOnClick: false, autolink: true }),
  Image.configure({ inline: false, allowBase64: false }),
  TaskList,
  TaskItem.configure({ nested: true }),
])

describe('待办正文转换', () => {
  it('无正文或无效 JSON 时返回空文档', () => {
    expect(parseTodoBody(null)).toEqual(EMPTY_TODO_DOC)
    expect(parseTodoBody('{}')).toEqual(EMPTY_TODO_DOC)
    expect(parseTodoBody('not-json')).toEqual(EMPTY_TODO_DOC)
  })

  it('保留合法的 Tiptap 文档', () => {
    const doc = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: '正文' }] }] }
    expect(parseTodoBody(JSON.stringify(doc))).toEqual(doc)
  })

  it('纯文本同步值去掉首尾空白', () => {
    expect(todoBodyText('  第一行\n第二行  ')).toBe('第一行\n第二行')
  })

  it('清除正文中的危险链接协议', () => {
    const doc = sanitizeTodoBody({
      type: 'doc',
      content: [{ type: 'paragraph', content: [{ type: 'text', text: 'x', marks: [{ type: 'link', attrs: { href: 'javascript:alert(1)' } }] }] }],
    })
    expect(doc.content?.[0].content?.[0].marks?.[0].attrs).toEqual({})
  })

  it('在 Markdown 与 Tiptap JSON 之间转换常用语法', () => {
    const doc = markdownToTodoBody('# 标题\n\n- **重点**\n\n[链接](https://example.com)', schema)
    expect(doc.content?.map((item) => item.type)).toEqual(['heading', 'bulletList', 'paragraph'])
    const taskDoc = markdownToTodoBody('- [ ] 待完成\n- [x] 已完成', schema)
    expect(taskDoc.content?.[0]).toMatchObject({ type: 'taskList' })
    const markdown = todoBodyToMarkdown({
      type: 'doc',
      content: [...(doc.content ?? []), ...(taskDoc.content ?? [])],
    }, schema)
    expect(markdown).toContain('# 标题')
    expect(markdown).toContain('**重点**')
    expect(markdown).toContain('- [ ] 待完成')
    expect(markdown).toContain('- [x] 已完成')
    expect(markdown).toContain('[链接](https://example.com)')
  })

  it('源码切换预览再切回时保留常用 Markdown 写法', () => {
    const source = '# 标题\n\n- **重点**\n  - 子项'
    const roundTrip = todoBodyToMarkdown(markdownToTodoBody(source, schema), schema)
    expect(roundTrip).toBe(source)
  })
})

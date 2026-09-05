import { describe, expect, it } from 'vitest'

import { EMPTY_TODO_DOC, parseTodoBody, sanitizeTodoBody, todoBodyText } from './body'

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
})

import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright'

const output = join(dirname(fileURLToPath(import.meta.url)), '../native/android/res/drawable-nodpi')
mkdirSync(output, { recursive: true })

const colors = { paper: '#FFF8ED', ink: '#29251F', secondary: '#796F63', accent: '#B3483D', rule: '#E6DACA', white: '#FFFDF8' }
const text = (x, y, value, size, color = colors.ink, weight = 400, family = 'sans') =>
  `<text x="${x}" y="${y}" font-family="${family === 'serif' ? 'Noto Serif CJK SC, SimSun, serif' : 'Microsoft YaHei, Noto Sans CJK SC, sans-serif'}" font-size="${size}" font-weight="${weight}" fill="${color}">${value}</text>`
const svg = (width, height, content) => `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="${width}" height="${height}" rx="32" fill="${colors.paper}"/><rect x="0" y="34" width="8" height="48" rx="4" fill="${colors.accent}"/>${content}</svg>`
const rule = (y, width, x = 24) => `<path d="M${x} ${y}H${width - x}" stroke="${colors.rule}" stroke-width="2"/>`
const header = (title, date, width) => [
  text(30, 64, title, 29, colors.ink, 700, 'serif'),
  text(width - 132, 62, date, 18, colors.secondary),
  rule(82, width, 30),
].join('')

const previews = {
  widget_guide_preview: [450, 336, svg(450, 336, [
    text(30, 64, '10月08日', 18, colors.secondary),
    `<rect x="330" y="36" width="88" height="32" rx="16" fill="#F4E4DC"/>`,
    text(346, 58, '下一节', 17, colors.accent, 700),
    text(30, 137, '高等数学', 34, colors.ink, 700, 'serif'),
    text(30, 177, '08:00 – 09:40', 23, colors.ink, 500),
    text(30, 211, '⌖  教三 · 204', 19, colors.secondary),
    rule(239, 450, 30),
    text(30, 273, '怎么又有课，我先叹口气。', 18, colors.secondary),
  ].join(''))],
  widget_today_preview: [450, 426, svg(450, 426, [
    header('今日课表', '10月08日', 450),
    ...[
      ['08:00', '高等数学', '教三 · 204'],
      ['10:00', '大学英语', '语音楼 · 301'],
      ['14:00', '体育', '体育馆'],
    ].flatMap(([time, title, room], index) => {
      const y = 145 + index * 83
      return [
        `<rect x="30" y="${y - 24}" width="4" height="49" rx="2" fill="${colors.accent}"/>`,
        text(48, y - 3, time, 16, colors.secondary, 500),
        text(152, y - 5, title, 22, colors.ink, 700),
        text(152, y + 21, room, 16, colors.secondary),
        ...(index < 2 ? [rule(y + 43, 450, 30)] : []),
      ]
    }),
    rule(398, 450, 30),
    text(30, 420, '今天的课是团购的吗？', 16, colors.secondary),
  ].join(''))],
  widget_overview_preview: [600, 384, svg(600, 384, [
    header('课业速览', '10月08日', 600),
    text(30, 124, '下一节课程', 18, colors.accent, 700),
    text(30, 166, '大学英语', 29, colors.ink, 700, 'serif'),
    text(30, 196, '10:00 – 11:40  ·  语音楼 301', 17, colors.secondary),
    rule(220, 600, 30),
    text(30, 254, '待办速览', 18, colors.accent, 700),
    text(30, 294, '完成数据结构作业', 23, colors.ink, 700),
    text(30, 323, '今天 23:00', 16, colors.secondary),
    rule(346, 600, 30),
    text(30, 374, '课和作业，一个都没落下。', 15, colors.secondary),
  ].join(''))],
  widget_todos_preview: [450, 426, svg(450, 426, [
    header('待办清单', '5 项待完成', 450),
    ...[
      ['数据结构作业', '今天 23:00'],
      ['实验报告', '明天'],
      ['复习第三章', '10月12日'],
      ['整理课堂笔记', '10月13日'],
      ['准备小组讨论', '10月15日'],
    ].flatMap(([title, due], index) => {
      const y = 128 + index * 51
      return [
        `<circle cx="36" cy="${y - 5}" r="4" fill="${index === 0 ? colors.accent : colors.rule}"/>`,
        text(50, y, title, 17, colors.ink, 600),
        text(324, y, due, 14, index === 0 ? colors.accent : colors.secondary),
        ...(index < 4 ? [rule(y + 17, 450, 30)] : []),
      ]
    }),
    rule(390, 450, 30),
    text(30, 417, '五件待办排队，我先叹口气。', 15, colors.secondary),
  ].join(''))],
}

const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ deviceScaleFactor: 1 })
  for (const [name, [width, height, markup]] of Object.entries(previews)) {
    await page.setViewportSize({ width, height })
    await page.setContent(markup)
    await page.locator('svg').screenshot({ path: join(output, `${name}.png`) })
  }
} finally {
  await browser.close()
}

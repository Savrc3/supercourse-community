import { expect, test, type Page } from '@playwright/test'

/** 在课表滑动区域上做一次横向手势，用于验证滑动切换后的布局回归。 */
async function swipeTimetable(page: Page, surfaceSelector: string) {
  const swipeBox = await page.locator(surfaceSelector).boundingBox()
  if (!swipeBox) throw new Error(`${surfaceSelector} 滑动区域未渲染`)
  await page.mouse.move(swipeBox.x + swipeBox.width * 0.75, swipeBox.y + swipeBox.height / 2)
  await page.mouse.down()
  await page.mouse.move(swipeBox.x + swipeBox.width * 0.25, swipeBox.y + swipeBox.height / 2, { steps: 5 })
  await page.mouse.up()
  await page.waitForTimeout(80)
}

/**
 * 回归：滑动切换的横向动画偏移（36px）不能被当成页面横向溢出。
 * 移动端 Chrome/WebView 一旦发现横向溢出会整体撑大布局视口（innerWidth/innerHeight 变大），
 * 固定底部导航随之被推到可见区域之外：图标还在，文字标签被裁掉。
 */
async function expectNavStableAfterSwipe(page: Page) {
  await page.waitForTimeout(600)
  const metrics = await page.evaluate(() => {
    const nav = document.querySelector<HTMLElement>('.mobile-nav')
    if (!nav) throw new Error('底部导航未渲染')
    const navRect = nav.getBoundingClientRect()
    const labels = [...nav.querySelectorAll<HTMLElement>('.mobile-tab span')].map((span) => span.getBoundingClientRect())
    const visual = window.visualViewport
    return {
      innerWidth: window.innerWidth,
      innerHeight: window.innerHeight,
      visualWidth: visual?.width ?? window.innerWidth,
      visualHeight: visual?.height ?? window.innerHeight,
      navWidth: navRect.width,
      navBottom: navRect.bottom,
      labelBottom: Math.max(...labels.map((label) => label.bottom)),
      scrollWidth: document.scrollingElement?.scrollWidth ?? window.innerWidth,
      tabWidths: [...nav.querySelectorAll<HTMLElement>('.mobile-tab')].map((tab) => Math.round(tab.getBoundingClientRect().width)),
    }
  })
  const viewport = page.viewportSize()
  expect(metrics.innerWidth).toBe(viewport?.width)
  expect(metrics.innerHeight).toBe(viewport?.height)
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.innerWidth)
  expect(metrics.navWidth).toBeLessThanOrEqual(metrics.visualWidth + 1)
  expect(metrics.navBottom).toBeLessThanOrEqual(metrics.visualHeight + 1)
  expect(metrics.labelBottom).toBeLessThanOrEqual(metrics.visualHeight - 1)
  expect(new Set(metrics.tabWidths).size).toBe(1)
  expect(metrics.tabWidths[0] * metrics.tabWidths.length).toBeLessThanOrEqual(metrics.visualWidth + 1)
}

test('首次访问进入模式向导，不阻塞于网络', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: '开始使用课序' })).toBeVisible()
  await expect(page.getByRole('button', { name: /本地使用/ })).toBeVisible()
  await expect(page.getByRole('button', { name: '连接服务器' })).toBeVisible()

  await page.getByRole('button', { name: /本地使用/ }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('heading', { name: '课表' })).toBeVisible()
  await expect(page.getByText('还没有课表。请先添加课程，或在管理页导入本地备份。')).toBeVisible()
  await expect(page.locator('.week-grid')).toHaveCount(0)
})

test('配对页可访问', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('sc_connection_profile', JSON.stringify({ mode: 'remote', serverUrl: 'http://localhost:8090/api' }))
  })
  await page.goto('/pair')
  await expect(page.getByRole('heading', { name: '登录课序' })).toBeVisible()
  await expect(page.getByRole('button', { name: '登录' })).toBeVisible()
})

test('移动端周视图一屏展示完整七天网格', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', '该回归项只验证移动端窄屏布局')

  await page.goto('/')
  await page.getByRole('button', { name: /本地使用/ }).click()
  await expect(page.getByRole('heading', { name: '课表' })).toBeVisible()

  await page.evaluate(async () => {
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('supercourse')
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    const transaction = database.transaction(['term', 'course', 'course_slot', 'lesson_period'], 'readwrite')
    transaction.objectStore('term').put({
      id: 'e2e-term', _rev: 1, _updated_at: null, _deleted_at: null,
      name: 'E2E 学期', label: null, start_date: '2026-08-31', weeks_total: 20,
      is_current: 1, archived_at: null,
    })
    transaction.objectStore('course').put({
      id: 'e2e-course', _rev: 1, _updated_at: null, _deleted_at: null,
      term_id: 'e2e-term', name: '移动端周视图回归课程', short_name: null,
      teacher: '测试教师', code: null, color: 1, credit: null, exam_at: null,
      exam_room: null, exam_note: null, textbook: null, grade_breakdown: null,
      note: null, sort_order: 0,
    })
    transaction.objectStore('course_slot').put({
      id: 'e2e-slot', _rev: 1, _updated_at: null, _deleted_at: null,
      course_id: 'e2e-course', weekday: 1, start_lesson: 1, end_lesson: 2,
      room: '测试教室', weeks: '{"ranges":[[1,20]],"only":[],"except":[],"parity":"all"}',
    })
    for (let lesson = 1; lesson <= 5; lesson += 1) {
      transaction.objectStore('lesson_period').put({
        id: `e2e-period-${lesson}`, _rev: 1, _updated_at: null, _deleted_at: null,
        term_id: 'e2e-term', lesson_no: lesson, start_time: `${String(8 + lesson).padStart(2, '0')}:00`,
        end_time: `${String(8 + lesson).padStart(2, '0')}:50`, big_period: lesson,
      })
    }
    await new Promise<void>((resolve, reject) => {
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => reject(transaction.error)
    })
  })

  await page.reload()
  await expect(page.getByRole('heading', { name: '课表' })).toBeVisible()
  await page.getByRole('button', { name: '切换周视图' }).click()
  await expect(page.locator('.week-grid')).toBeVisible()
  await expect(page.locator('.week-scroll')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '+ 添加课程', exact: true })).toHaveCSS('white-space', 'nowrap')

  const metrics = await page.locator('.week-grid').evaluate((element) => ({
    width: element.getBoundingClientRect().width,
    viewportWidth: window.innerWidth,
  }))
  expect(metrics.width).toBeLessThanOrEqual(metrics.viewportWidth + 1)
  await expect(page.locator('.week-head-cell')).toHaveCount(7)
  await expect(page.locator('.week-course .wc-time')).toHaveCount(0)

  // 周视图共用同一套横向切换动画，滑动后底部导航同样必须完整可见。
  await swipeTimetable(page, '.week-grid')
  await expectNavStableAfterSwipe(page)
})

test('移动端单日视图完整显示五个大节，不被底部导航遮挡', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', '该回归项只验证移动端窄屏布局')
  await page.setViewportSize({ width: 360, height: 800 })

  await page.goto('/')
  await page.getByRole('button', { name: /本地使用/ }).click()
  await expect(page.getByRole('heading', { name: '课表' })).toBeVisible()

  await page.evaluate(async () => {
    const now = new Date()
    const weekday = now.getDay() || 7
    const monday = new Date(now)
    monday.setDate(now.getDate() - weekday + 1)
    const startDate = `${monday.getFullYear()}-${String(monday.getMonth() + 1).padStart(2, '0')}-${String(monday.getDate()).padStart(2, '0')}`
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('supercourse')
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    const transaction = database.transaction(['term', 'course', 'course_slot', 'lesson_period'], 'readwrite')
    transaction.objectStore('term').put({
      id: 'e2e-day-term', _rev: 1, _updated_at: null, _deleted_at: null,
      name: 'E2E 单日视图学期', label: null, start_date: startDate, weeks_total: 20,
      is_current: 1, archived_at: null,
    })
    transaction.objectStore('course').put({
      id: 'e2e-day-course', _rev: 1, _updated_at: null, _deleted_at: null,
      term_id: 'e2e-day-term', name: '移动端单日视图课程', short_name: null,
      teacher: '测试教师', code: null, color: 1, credit: null, exam_at: null,
      exam_room: null, exam_note: null, textbook: null, grade_breakdown: null,
      note: null, sort_order: 0,
    })
    for (let lesson = 1; lesson <= 5; lesson += 1) {
      transaction.objectStore('course_slot').put({
        id: `e2e-day-slot-${lesson}`, _rev: 1, _updated_at: null, _deleted_at: null,
        course_id: 'e2e-day-course', weekday, start_lesson: lesson, end_lesson: lesson,
        room: '测试教室', weeks: '{"ranges":[[1,20]],"only":[],"except":[],"parity":"all"}',
      })
      transaction.objectStore('lesson_period').put({
        id: `e2e-day-period-${lesson}`, _rev: 1, _updated_at: null, _deleted_at: null,
        term_id: 'e2e-day-term', lesson_no: lesson, start_time: `${String(7 + lesson).padStart(2, '0')}:00`,
        end_time: `${String(7 + lesson).padStart(2, '0')}:50`, big_period: lesson,
      })
    }
    await new Promise<void>((resolve, reject) => {
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => reject(transaction.error)
    })
  })

  await page.reload()
  await expect(page.locator('.day-grid')).toBeVisible()
  await expect(page.locator('.day-period')).toHaveCount(5)

  // 查看其它日期时不再插入额外的“回到今天”布局行，但真实今天仍有明确标记。
  await page.locator('.day-tab').nth(1).click()
  await expect(page.locator('.today-link')).toHaveCount(0)
  await expect(page.locator('.today-mark')).toHaveCount(1)

  // 回归：真正滑动切换日期后，固定底部导航不能被动画层裁剪或推到视口外。
  await swipeTimetable(page, '.day-grid')
  const navDuringSwipe = await page.locator('.mobile-nav').evaluate((element) => {
    const rect = element.getBoundingClientRect()
    return {
      top: rect.top,
      bottom: rect.bottom,
      height: rect.height,
      viewportHeight: window.innerHeight,
      paddingBottom: Number.parseFloat(getComputedStyle(element).paddingBottom),
      tabContentBottom: Math.max(
        ...[...element.querySelectorAll<HTMLElement>('.mobile-tab')].map((tab) => tab.getBoundingClientRect().bottom),
      ),
    }
  })
  expect(navDuringSwipe.height).toBeGreaterThanOrEqual(60)
  expect(navDuringSwipe.top).toBeLessThanOrEqual(navDuringSwipe.viewportHeight)
  expect(navDuringSwipe.bottom).toBeLessThanOrEqual(navDuringSwipe.viewportHeight + 1)
  expect(navDuringSwipe.paddingBottom).toBeGreaterThanOrEqual(16)
  expect(navDuringSwipe.tabContentBottom).toBeLessThanOrEqual(navDuringSwipe.viewportHeight - 1)
  await page.waitForTimeout(350)

  const metrics = await page.evaluate(() => {
    const rows = [...document.querySelectorAll<HTMLElement>('.day-period')]
    const nav = document.querySelector<HTMLElement>('.mobile-nav')
    const last = rows.at(-1)
    if (!last || !nav) throw new Error('单日视图或底部导航未渲染')
    return {
      lastBottom: last.getBoundingClientRect().bottom,
      navTop: nav.getBoundingClientRect().top,
    }
  })
  expect(metrics.lastBottom).toBeLessThanOrEqual(metrics.navTop + 1)

  // 回归：滑动结束后布局视口不能被横向动画撑大，底部导航文字必须留在可见区域内。
  await expectNavStableAfterSwipe(page)
})

test('待办 Markdown 预览保留标题、列表标记和嵌套层级', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: /本地使用/ }).click()
  await expect(page.getByRole('heading', { name: '课表' })).toBeVisible()

  await page.evaluate(async () => {
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('supercourse')
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    const transaction = database.transaction('todo', 'readwrite')
    transaction.objectStore('todo').put({
      id: 'e2e-markdown-todo', _rev: 1, _updated_at: null, _deleted_at: null,
      course_id: null, kind: 'todo', title: 'Markdown 渲染回归',
      body: JSON.stringify({
        type: 'doc',
        content: [
          { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: '大学物理（2）课程要求' }] },
          { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: '1. 课程考核' }] },
          { type: 'paragraph', content: [{ type: 'text', text: '教学评价：过程性评价与终结性评价结合。' }] },
          { type: 'bulletList', content: [{
            type: 'listItem',
            content: [
              { type: 'paragraph', content: [{ type: 'text', text: '平时成绩', marks: [{ type: 'bold' }] }] },
              { type: 'bulletList', content: [{ type: 'listItem', content: [{ type: 'paragraph', content: [{ type: 'text', text: '单元测验：20分' }] }] }] },
            ],
          }] },
        ],
      }),
      body_text: '大学物理（2）课程要求\n1. 课程考核\n教学评价：过程性评价与终结性评价结合。\n平时成绩\n单元测验：20分',
      due_at: null, start_at: null, due_all_day: 1, repeat: null, status: '0', done_at: null,
      priority: 1, tags: '[]', remind_mode: 'inherit', remind_offsets: null, sort_order: 0,
      created_at: '2026-09-06T00:00:00',
    })
    await new Promise<void>((resolve, reject) => {
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => reject(transaction.error)
    })
  })

  await page.goto('/todo/e2e-markdown-todo')
  await expect(page.getByRole('heading', { name: 'Markdown 渲染回归' })).toBeVisible()

  await page.getByRole('button', { name: 'Markdown源码' }).click()
  await page.locator('textarea[aria-label="Markdown源码"]').fill('# 大学物理（2）课程要求\n\n## 1. 课程考核\n\n教学评价：过程性评价与终结性评价结合。\n\n- **平时成绩**\n  - 单元测验：20分')
  await page.getByRole('button', { name: '预览 Markdown' }).click()
  await expect(page.locator('.ProseMirror h1')).toHaveText('大学物理（2）课程要求')
  await expect(page.locator('.ProseMirror h2')).toHaveText('1. 课程考核')

  const styles = await page.locator('.ProseMirror').evaluate((editor) => {
    const heading = editor.querySelector('h1')
    const list = editor.querySelector('ul:not([data-type="taskList"])')
    const nestedList = editor.querySelector('li > ul')
    if (!heading || !list || !nestedList) throw new Error('Markdown 节点未生成')
    return {
      headingSize: Number.parseFloat(getComputedStyle(heading).fontSize),
      headingWeight: Number.parseInt(getComputedStyle(heading).fontWeight, 10),
      listStyle: getComputedStyle(list).listStyleType,
      nestedListStyle: getComputedStyle(nestedList).listStyleType,
    }
  })
  expect(styles.headingSize).toBeGreaterThan(20)
  expect(styles.headingWeight).toBeGreaterThanOrEqual(650)
  expect(styles.listStyle).toBe('disc')
  expect(styles.nestedListStyle).toBe('circle')
})

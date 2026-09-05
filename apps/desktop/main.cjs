const fs = require('node:fs')
const http = require('node:http')
const path = require('node:path')
const { execFile } = require('node:child_process')
const {
  app,
  BrowserWindow,
  Menu,
  nativeImage,
  Notification,
  Tray,
  ipcMain,
  screen,
} = require('electron')

const { normalizeWindowBounds, readJson } = require('./state.cjs')

const APP_ID = 'icu.savrc3.supercourse'
const PORT_FALLBACK = 4173
const gotLock = app.requestSingleInstanceLock()
let mainWindow = null
let tray = null
let staticServer = null
let appUrl = ''
let isQuitting = false
let saveTimer = null
const startHidden = process.argv.includes('--hidden')

if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', (_event, commandLine) => {
    showMainWindow(commandLine.includes('--settings') ? '/settings' : undefined)
  })
  app.whenReady().then(bootstrap).catch((error) => {
    console.error('desktop bootstrap failed', error)
    app.quit()
  })
}

async function bootstrap() {
  const settings = loadSettings()
  const port = await startStaticServer(Number(settings.port) || PORT_FALLBACK)
  appUrl = `http://localhost:${port}`
  settings.port = port
  saveSettings(settings)
  createMainWindow(settings)
  createTray(settings)
}

function loadSettings() {
  const dir = app.getPath('userData')
  return {
    openAtLogin: false,
    ...readJson(readFile(path.join(dir, 'desktop-settings.json')), {}),
    window: readJson(readFile(path.join(dir, 'window-state.json')), {}),
  }
}

function saveSettings(settings) {
  const dir = app.getPath('userData')
  fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(path.join(dir, 'desktop-settings.json'), JSON.stringify({
    port: settings.port,
    openAtLogin: Boolean(settings.openAtLogin),
  }))
}

function saveWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) return
  const bounds = mainWindow.getBounds()
  fs.writeFileSync(path.join(app.getPath('userData'), 'window-state.json'), JSON.stringify(bounds))
}

function createMainWindow(settings) {
  const workArea = screen.getPrimaryDisplay().workArea
  const bounds = normalizeWindowBounds(settings.window, workArea)
  mainWindow = new BrowserWindow({
    ...bounds,
    show: false,
    minWidth: 960,
    minHeight: 640,
    title: '课序',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.cjs'),
    },
  })
  void mainWindow.loadURL(appUrl)
  mainWindow.once('ready-to-show', () => {
    if (!startHidden) mainWindow?.show()
  })
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault()
      mainWindow?.hide()
      saveWindowState()
    }
  })
  mainWindow.on('resize', scheduleWindowSave)
  mainWindow.on('move', scheduleWindowSave)
}

function scheduleWindowSave() {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(saveWindowState, 250)
}

function showMainWindow(route) {
  if (!mainWindow || mainWindow.isDestroyed()) return
  if (route) void mainWindow.loadURL(`${appUrl}${route}`)
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
}

function createTray(settings) {
  const iconPath = app.isPackaged
    ? path.join(process.resourcesPath, 'tray.png')
    : path.resolve(__dirname, '../web/public/pwa/icon-192.png')
  const icon = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 })
  tray = new Tray(icon)
  tray.setToolTip('课序')
  tray.on('double-click', () => showMainWindow())
  rebuildTrayMenu(settings)
}

function rebuildTrayMenu(settings) {
  tray?.setContextMenu(Menu.buildFromTemplate([
    { label: '打开课序', click: () => showMainWindow() },
    { type: 'separator' },
    {
      label: '开机自启',
      type: 'checkbox',
      checked: Boolean(settings.openAtLogin),
      click: (item) => setOpenAtLogin(settings, item.checked),
    },
    { label: '检查更新', click: () => showMainWindow('/profile') },
    { type: 'separator' },
    { label: '退出', click: () => { isQuitting = true; app.quit() } },
  ]))
}

function setOpenAtLogin(settings, enabled) {
  settings.openAtLogin = enabled
  saveSettings(settings)
  if (process.platform === 'win32') {
    try {
      app.setLoginItemSettings({ openAtLogin: enabled, path: process.execPath, args: ['--hidden'] })
    } catch {
      updateWindowsRunKey(enabled)
    }
  }
  rebuildTrayMenu(settings)
}

function updateWindowsRunKey(enabled) {
  if (process.platform !== 'win32') return
  const key = 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run'
  const args = enabled
    ? ['/add', key, '/v', APP_ID, '/t', 'REG_SZ', '/d', `"${process.execPath}" --hidden`, '/f']
    : ['/delete', key, '/v', APP_ID, '/f']
  execFile('reg.exe', args, () => {})
}

function createStaticServer(preferredPort) {
  const root = app.isPackaged
    ? path.join(process.resourcesPath, 'web', 'dist')
    : path.resolve(__dirname, '../web/dist')
  const tryListen = (port) => new Promise((resolve, reject) => {
    const server = http.createServer((request, response) => serveFile(root, request, response))
    server.once('error', reject)
    server.listen(port, 'localhost', () => resolve({ server, port: server.address().port }))
  })
  return tryListen(preferredPort).catch((error) => {
    if (error.code !== 'EADDRINUSE') throw error
    return tryListen(0)
  })
}

async function startStaticServer(preferredPort) {
  const result = await createStaticServer(preferredPort)
  staticServer = result.server
  return result.port
}

function serveFile(root, request, response) {
  let requestUrl
  let pathname
  try {
    requestUrl = new URL(request.url || '/', 'http://localhost')
    pathname = decodeURIComponent(requestUrl.pathname)
  } catch {
    response.writeHead(400)
    response.end('Bad Request')
    return
  }
  if (pathname === '/' || !path.extname(pathname)) pathname = '/index.html'
  const file = path.resolve(root, `.${pathname}`)
  const relative = path.relative(root, file)
  if (relative.startsWith('..') || path.isAbsolute(relative) || !fs.existsSync(file)) {
    response.writeHead(404)
    response.end('Not Found')
    return
  }
  response.setHeader('X-Content-Type-Options', 'nosniff')
  response.setHeader('X-Frame-Options', 'DENY')
  response.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin')
  response.setHeader('Content-Security-Policy', "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' https: http://localhost:* http://localhost:*; font-src 'self' data:; form-action 'self'")
  response.setHeader('Content-Type', contentType(file))
  fs.createReadStream(file).pipe(response)
}

function contentType(file) {
  const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.webmanifest': 'application/manifest+json' }
  return types[path.extname(file).toLowerCase()] || 'application/octet-stream'
}

function readFile(file) {
  try { return fs.readFileSync(file, 'utf8') } catch { return '' }
}

ipcMain.on('desktop-show-main', () => showMainWindow())
ipcMain.on('desktop-notify', (_event, payload = {}) => {
  if (!Notification.isSupported()) return
  const notification = new Notification({ title: String(payload.title || '课序'), body: String(payload.body || '') })
  notification.on('click', () => showMainWindow(typeof payload.todoId === 'string' ? `/todo/${payload.todoId}` : undefined))
  notification.show()
})

app.on('before-quit', () => {
  isQuitting = true
  if (saveTimer) clearTimeout(saveTimer)
  saveWindowState()
  staticServer?.close()
})

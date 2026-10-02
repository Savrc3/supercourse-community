import { appendFileSync, copyFileSync, cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

import { makePng } from '../../web/scripts/gen-icons.mjs'

const mobileRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const androidRoot = join(mobileRoot, 'android')
const capacitorCli = join(mobileRoot, '..', '..', 'node_modules', '@capacitor', 'cli', 'bin', 'capacitor')
const appVersion = JSON.parse(readFileSync(join(mobileRoot, 'package.json'), 'utf8')).version
const versionCode = appVersion
  .split('.')
  .map(Number)
  .reduce((value, part, index) => value + part * [10000, 100, 1][index], 0)

if (!existsSync(androidRoot)) {
  execFileSync(process.execPath, [capacitorCli, 'add', 'android'], { cwd: mobileRoot, stdio: 'inherit' })
}

const propertiesPath = join(androidRoot, 'gradle.properties')
const marker = 'android.overridePathCheck=true'
const properties = existsSync(propertiesPath) ? readFileSync(propertiesPath, 'utf8') : ''
if (!properties.includes(marker)) {
  appendFileSync(propertiesPath, `\n${marker}\n`)
}

const gradlePath = join(androidRoot, 'app', 'build.gradle')
if (existsSync(gradlePath)) {
  const gradle = readFileSync(gradlePath, 'utf8')
  const nextGradle = gradle
    .replace(/versionCode \d+/, `versionCode ${versionCode}`)
    .replace(/versionName "[^"]+"/, `versionName "${appVersion}"`)
  if (nextGradle !== gradle) writeFileSync(gradlePath, nextGradle)
}

const manifestPath = join(androidRoot, 'app', 'src', 'main', 'AndroidManifest.xml')
if (existsSync(manifestPath)) {
  let manifest = readFileSync(manifestPath, 'utf8')
  const permission = '    <uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES" />'
  if (!manifest.includes('android.permission.REQUEST_INSTALL_PACKAGES')) {
    manifest = manifest.replace('</manifest>', `${permission}\n</manifest>`)
  }

  const bootPermission = '    <uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />'
  if (!manifest.includes('android.permission.RECEIVE_BOOT_COMPLETED')) {
    manifest = manifest.replace('</manifest>', `${bootPermission}\n</manifest>`)
  }

  const marker = '<!-- supercourse-android-widgets -->'
  if (!manifest.includes(marker)) {
    const components = `    ${marker}
    <receiver android:name=".widgets.NextClassWidgetProvider" android:exported="true" android:label="上课指引">
      <intent-filter><action android:name="android.appwidget.action.APPWIDGET_UPDATE" /></intent-filter>
      <meta-data android:name="android.appwidget.provider" android:resource="@xml/widget_guide_info" />
    </receiver>
    <receiver android:name=".widgets.TodayWidgetProvider" android:exported="true" android:label="今日课表">
      <intent-filter><action android:name="android.appwidget.action.APPWIDGET_UPDATE" /></intent-filter>
      <meta-data android:name="android.appwidget.provider" android:resource="@xml/widget_today_info" />
    </receiver>
    <receiver android:name=".widgets.OverviewWidgetProvider" android:exported="true" android:label="课业速览">
      <intent-filter><action android:name="android.appwidget.action.APPWIDGET_UPDATE" /></intent-filter>
      <meta-data android:name="android.appwidget.provider" android:resource="@xml/widget_overview_info" />
    </receiver>
    <receiver android:name=".widgets.TodoWidgetProvider" android:exported="true" android:label="待办清单">
      <intent-filter><action android:name="android.appwidget.action.APPWIDGET_UPDATE" /></intent-filter>
      <meta-data android:name="android.appwidget.provider" android:resource="@xml/widget_todos_info" />
    </receiver>
    <service android:name=".widgets.WidgetRemoteViewsService" android:exported="true" android:permission="android.permission.BIND_REMOTEVIEWS" />
    <receiver android:name=".widgets.WidgetRefreshReceiver" android:exported="false" />
    <receiver android:name=".widgets.WidgetBootReceiver" android:exported="false">
      <intent-filter><action android:name="android.intent.action.BOOT_COMPLETED" /></intent-filter>
    </receiver>`
    manifest = manifest.replace('</application>', `${components}\n  </application>`)
  }
  writeFileSync(manifestPath, manifest)
}

// Capacitor's android/ tree is generated and ignored; keep all widget Java/resources in this tracked source tree.
const nativeRoot = join(mobileRoot, 'native', 'android')
const appRoot = join(androidRoot, 'app', 'src', 'main')
const javaRoot = join(appRoot, 'java')
for (const entry of readdirSync(join(nativeRoot, 'java'), { withFileTypes: true })) {
  if (!entry.isFile() || !entry.name.endsWith('.java')) continue
  const source = join(nativeRoot, 'java', entry.name)
  const packageName = readFileSync(source, 'utf8').match(/^package\s+([\w.]+);/m)?.[1]
  if (!packageName) throw new Error(`Native Android source has no package declaration: ${entry.name}`)
  const destination = join(javaRoot, ...packageName.split('.'))
  mkdirSync(destination, { recursive: true })
  copyFileSync(source, join(destination, entry.name))
}
cpSync(join(nativeRoot, 'res'), join(appRoot, 'res'), { recursive: true, force: true })
// Exercise RemoteViews inflation on Android itself; compilation does not enforce its view allowlist.
cpSync(join(nativeRoot, 'androidTest'), join(androidRoot, 'app', 'src', 'androidTest'), { recursive: true, force: true })

// Android 启动图标与 Web/Desktop 共用同一份品牌图形，避免 Capacitor 初始图标回退成旧菱形。
const iconSizes = { ldpi: 36, mdpi: 48, hdpi: 72, xhdpi: 96, xxhdpi: 144, xxxhdpi: 192 }
const resRoot = join(androidRoot, 'app', 'src', 'main', 'res')
for (const [density, size] of Object.entries(iconSizes)) {
  const iconDir = join(resRoot, `mipmap-${density}`)
  mkdirSync(iconDir, { recursive: true })
  const png = makePng(size, 0.18)
  writeFileSync(join(iconDir, 'ic_launcher.png'), png)
  writeFileSync(join(iconDir, 'ic_launcher_round.png'), png)
}
writeFileSync(join(mobileRoot, 'resources', 'icon.png'), makePng(512, 0.18))

// 保留完整方形品牌图标，移除 Capacitor 默认的 v26 自适应菱形资源，确保新旧 Android 都显示同一图形。
const adaptiveIconDir = join(resRoot, 'mipmap-anydpi-v26')
rmSync(join(adaptiveIconDir, 'ic_launcher.xml'), { force: true })
rmSync(join(adaptiveIconDir, 'ic_launcher_round.xml'), { force: true })

writeFileSync(join(androidRoot, '.supercourse-ready'), 'generated by prepare-android.mjs\n')

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { App as CapacitorApp } from '@capacitor/app'
import { Capacitor } from '@capacitor/core'

import { checkForAppUpdate, downloadAndInstallAndroidUpdate } from '../../core/app-update'
import { apiFetch } from '../../core/http'
import { sync } from '../../core/sync'

interface Device {
  id: string
  name: string | null
  platform: string | null
  last_seen_at: string | null
  revoked_at: string | null
  is_current: boolean
}

const devices = ref<Device[]>([])
const loaded = ref(false)
const busy = ref<Record<string, boolean>>({})
const editing = ref<string | null>(null)
const editName = ref('')
const appVersion = ref('')
const latestVersion = ref('')
const updateUrl = ref<string | null>(null)
const updateMessage = ref('')
const checkingUpdate = ref(false)
const installingUpdate = ref(false)

async function loadDevices() {
  try {
    const resp = await apiFetch('/devices', {
      headers: { Authorization: `Bearer ${sync.token}` },
    })
    if (resp.ok) {
      const data = await resp.json()
      devices.value = data.devices ?? []
    }
  } catch {
    // 忽略，保持已有列表
  } finally {
    loaded.value = true
  }
}

async function revoke(id: string) {
  busy.value[id] = true
  try {
    const resp = await apiFetch(`/devices/${id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${sync.token}` },
    })
    if (resp.ok) {
      await loadDevices()
    }
  } finally {
    busy.value[id] = false
  }
}

function startEdit(d: Device) {
  editing.value = d.id
  editName.value = d.name ?? ''
}

async function saveName(id: string) {
  const name = editName.value.trim()
  if (!name) {
    editing.value = null
    return
  }
  busy.value[id] = true
  try {
    const resp = await apiFetch(`/devices/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${sync.token}` },
      body: JSON.stringify({ name }),
    })
    if (resp.ok) {
      await loadDevices()
    }
  } finally {
    busy.value[id] = false
    editing.value = null
  }
}

async function checkUpdate() {
  checkingUpdate.value = true
  updateMessage.value = ''
  try {
    const result = await checkForAppUpdate()
    appVersion.value = result.current
    latestVersion.value = result.latest
    updateUrl.value = result.url
    updateMessage.value = result.available
      ? result.url ? '发现新版本，可以下载安装。' : '发现新版本，但服务器尚未配置 APK 下载地址。'
      : '当前已是最新版本。'
  } catch {
    updateMessage.value = '版本检查失败，请联网后重试。'
  } finally {
    checkingUpdate.value = false
  }
}

async function installUpdate() {
  if (!updateUrl.value) return
  installingUpdate.value = true
  updateMessage.value = '正在下载更新…'
  try {
    await downloadAndInstallAndroidUpdate(updateUrl.value)
    updateMessage.value = '已交给系统安装器，请按提示完成更新。'
  } catch {
    updateMessage.value = '下载或打开安装器失败，请稍后重试。'
  } finally {
    installingUpdate.value = false
  }
}

onMounted(() => {
  void loadDevices()
  if (Capacitor.isNativePlatform()) void CapacitorApp.getInfo().then((info) => { appVersion.value = info.version })
  void checkUpdate()
})
</script>

<template>
  <section class="profile">
    <header class="view-head">
      <div>
        <h1>我的</h1>
        <p>账号下的设备会自动同步</p>
      </div>
    </header>

      <div class="panel">
      <h2>设备</h2>
      <p
        v-if="!loaded"
        class="muted"
      >正在加载…</p>
      <p
        v-else-if="devices.length === 0"
        class="muted"
      >暂无设备</p>
      <ul
        v-else
        class="dev-list"
      >
        <li
          v-for="d in devices"
          v-show="!d.revoked_at"
          :key="d.id"
          class="dev-item"
        >
          <div class="dev-info">
            <template v-if="editing === d.id">
              <input
                v-model="editName"
                class="name-input"
                maxlength="60"
                @keyup.enter="saveName(d.id)"
                @keyup.esc="editing = null"
              >
            </template>
            <template v-else>
              <span class="dev-name">
                {{ d.name || '未命名设备' }}
                <em
                  v-if="d.is_current"
                  class="current"
                >当前</em>
              </span>
            </template>
            <span class="muted">{{ d.platform || '' }}</span>
          </div>
          <div class="dev-actions">
            <button
              v-if="editing === d.id"
              class="ghost-btn"
              :disabled="busy[d.id]"
              @click="saveName(d.id)"
            >保存</button>
            <button
              v-else
              class="ghost-btn"
              @click="startEdit(d)"
            >改名</button>
            <button
              class="ghost-btn danger"
              :disabled="busy[d.id] || d.is_current"
              @click="revoke(d.id)"
            >{{ d.is_current ? '当前' : '吊销' }}</button>
          </div>
        </li>
      </ul>
    </div>

    <div class="panel">
      <h2>应用版本</h2>
      <p class="muted">当前版本：{{ appVersion || '读取中…' }}<template v-if="latestVersion"> · 最新版本：{{ latestVersion }}</template></p>
      <div class="dev-actions update-actions">
        <button
          class="ghost-btn"
          :disabled="checkingUpdate || installingUpdate"
          @click="checkUpdate"
        >{{ checkingUpdate ? '检查中…' : '检查更新' }}</button>
        <button
          v-if="updateUrl"
          class="primary-btn"
          :disabled="installingUpdate"
          @click="installUpdate"
        >{{ installingUpdate ? '下载中…' : '下载安装' }}</button>
      </div>
      <p
        v-if="updateMessage"
        class="muted update-message"
      >{{ updateMessage }}</p>
    </div>
  </section>
</template>

<style scoped>
.profile {
  padding-top: 4px;
}
.panel {
  margin-top: 18px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
}
.panel h2 {
  margin: 0 0 8px;
  font-size: 16px;
}
.muted {
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}
.primary-btn {
  margin-top: 12px;
  height: 40px;
  padding: 0 16px;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font-weight: 600;
}
.update-actions { margin-top: 12px; }
.update-message { margin: 10px 0 0; }
.primary-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.pairing-code {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.code {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 2px;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}
.err {
  color: var(--danger);
  font-size: 13px;
  margin-top: 10px;
}
.dev-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.dev-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
.dev-item:last-child {
  border-bottom: none;
}
.dev-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.dev-actions {
  display: flex;
  gap: 6px;
}
.name-input {
  height: 32px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: 14px;
}
.dev-name {
  font-weight: 600;
  color: var(--text);
}
.current {
  font-style: normal;
  font-size: 12px;
  color: var(--accent);
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--accent-soft);
}
.ghost-btn {
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
}
.ghost-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.ghost-btn.danger {
  color: var(--danger);
}
</style>

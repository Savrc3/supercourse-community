<script setup lang="ts">
import { ref } from 'vue'
import { Capacitor } from '@capacitor/core'
import { useRouter } from 'vue-router'

import { isSafeRemoteUrl, setConnectionProfile } from '../../core/connection'
import { sync } from '../../core/sync'

const router = useRouter()
const serverUrl = ref('')
const error = ref('')

function chooseLocal() {
  sync.stop()
  sync.clearToken()
  setConnectionProfile({ mode: 'local' })
  void router.replace(Capacitor.isNativePlatform() && !localStorage.getItem('sc_onboarding_done') ? '/onboarding' : '/')
}

function chooseRemote() {
  const value = serverUrl.value.trim()
  if (!isSafeRemoteUrl(value)) {
    error.value = '请输入 HTTPS 服务器地址（本机开发可使用 http://localhost）'
    return
  }
  setConnectionProfile({ mode: 'remote', serverUrl: value })
  sync.clearToken()
  sync.resetCursor()
  void router.replace('/login')
}
</script>

<template>
  <section class="setup-page">
    <h1>开始使用超课表</h1>
    <p class="setup-desc">你可以只在当前设备使用，也可以连接自己的服务器同步。</p>
    <div class="setup-options">
      <button class="setup-card" type="button" @click="chooseLocal">
        <strong>本地使用</strong>
        <span>无需账号和服务器，数据只保存在当前设备。</span>
      </button>
      <form class="setup-card remote-card" @submit.prevent="chooseRemote">
        <strong>连接自己的服务器</strong>
        <span>填写你的后端地址，再用账号登录同步。</span>
        <input v-model="serverUrl" type="url" placeholder="https://example.com" autocomplete="url">
        <button class="primary-btn" type="submit">连接服务器</button>
      </form>
    </div>
    <p v-if="error" class="setup-error">{{ error }}</p>
  </section>
</template>

<style scoped>
.setup-page { max-width: 660px; margin: 8vh auto 0; }
.setup-page h1 { margin: 0 0 10px; font-size: 26px; }
.setup-desc, .setup-card span { color: var(--text-secondary); font-size: 14px; line-height: 1.7; }
.setup-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 24px; }
.setup-card { display: grid; gap: 8px; min-height: 170px; padding: 20px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); color: var(--text); font: inherit; text-align: left; cursor: pointer; }
.setup-card:hover { border-color: var(--accent); }
.remote-card { cursor: default; }
.remote-card:hover { border-color: var(--line); }
.remote-card input { width: 100%; min-height: 40px; padding: 0 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; }
.primary-btn { min-height: 40px; border: 0; border-radius: 8px; background: var(--accent); color: #fff; font: inherit; font-weight: 600; cursor: pointer; }
.setup-error { margin-top: 14px; color: var(--danger); font-size: 13px; }
@media (max-width: 620px) { .setup-options { grid-template-columns: 1fr; } .setup-page { margin-top: 4vh; } }
</style>

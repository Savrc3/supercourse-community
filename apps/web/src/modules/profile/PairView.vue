<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { apiFetch } from '../../core/http'
import { defaultRemoteApiBase, getConnectionProfile, setConnectionProfile } from '../../core/connection'
import { sync } from '../../core/sync'

const router = useRouter()
const mode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const status = ref<'idle' | 'loading' | 'error'>('idle')
const message = ref('')
const hasAccount = ref(true)

onMounted(async () => {
  try {
    const response = await apiFetch('/auth/status')
    if (response.ok) {
      const data = await response.json() as { registration_enabled?: boolean }
      hasAccount.value = data.registration_enabled === true
      if (!hasAccount.value) mode.value = 'login'
    }
  } catch {
    // 提交时再给出具体网络错误。
  }
})

async function submit() {
  if (!username.value.trim() || password.value.length < 8) return
  status.value = 'loading'
  message.value = ''
  try {
    const response = await apiFetch(`/auth/${mode.value === 'register' ? 'register' : 'login'}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username.value.trim(), password: password.value, device_name: deviceName(), platform: platformName() }),
    })
    const data = await response.json().catch(() => ({})) as { token?: string; detail?: { message?: string } }
    if (!response.ok || !data.token) {
      status.value = 'error'
      message.value = data.detail?.message ?? '登录失败，请检查后端服务'
      return
    }
    sync.stop()
    const profile = getConnectionProfile()
    setConnectionProfile({ mode: 'remote', serverUrl: profile?.serverUrl ?? defaultRemoteApiBase() })
    sync.setBaseUrl(getConnectionProfile()?.serverUrl ?? defaultRemoteApiBase())
    sync.setToken(data.token)
    sync.resetCursor()
    await sync.bootstrap()
    sync.start()
    await router.push('/')
  } catch {
    status.value = 'error'
    message.value = '网络异常，请确认后端已启动'
  }
}

function deviceName(): string {
  const ua = navigator.userAgent
  if (/android/i.test(ua)) return '手机'
  if (/windows/i.test(ua)) return '电脑'
  if (/iphone|ipad/i.test(ua)) return 'iPhone'
  return '浏览器'
}

function platformName(): string {
  if (/android/i.test(navigator.userAgent)) return 'android'
  if (/windows/i.test(navigator.userAgent)) return 'windows'
  return 'web'
}
</script>

<template>
  <section class="login-page">
    <h1>{{ mode === 'register' ? '创建账号' : '登录超课表' }}</h1>
    <p class="login-desc">同一账号登录的电脑、手机会自动同步，不需要配对码。</p>
    <form class="login-form" @submit.prevent="submit">
      <label>账号<input v-model="username" autocomplete="username" required placeholder="输入账号"></label>
      <label>密码<input v-model="password" autocomplete="current-password" minlength="8" required type="password" placeholder="至少 8 位"></label>
      <button class="primary-btn" type="submit" :disabled="status === 'loading' || !username.trim() || password.length < 8">{{ status === 'loading' ? '处理中…' : mode === 'register' ? '创建并登录' : '登录' }}</button>
    </form>
    <p v-if="status === 'error'" class="login-error">{{ message }}</p>
    <button v-if="hasAccount" class="switch-btn" type="button" @click="mode = mode === 'login' ? 'register' : 'login'; message = ''">{{ mode === 'login' ? '首次使用？创建账号' : '已有账号？返回登录' }}</button>
    <p class="login-warn">账号是本项目的单用户入口；密码只用于登录，不会写入同步数据。</p>
  </section>
</template>

<style scoped>
.login-page { max-width: 420px; margin: 0 auto; padding-top: 6vh; }
.login-page h1 { margin: 0 0 10px; font-size: 24px; }
.login-desc, .login-warn { color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.login-form { display: grid; gap: 14px; margin-top: 22px; }
.login-form label { display: grid; gap: 6px; color: var(--text-secondary); font-size: 13px; }
.login-form input { min-height: 42px; padding: 0 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; }
.primary-btn { min-height: 42px; border: 0; border-radius: 8px; background: var(--accent); color: #fff; font: inherit; font-weight: 600; cursor: pointer; }
.primary-btn:disabled { cursor: not-allowed; opacity: .55; }
.switch-btn { margin-top: 16px; border: 0; background: transparent; color: var(--accent); cursor: pointer; font: inherit; }
.login-error { margin-top: 12px; color: var(--danger); font-size: 13px; }
.login-warn { margin-top: 22px; font-size: 12px; }
</style>

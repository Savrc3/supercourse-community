<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { requestLocalNotificationPermission } from '../../core/notifications'

const router = useRouter()
const permission = ref('未设置')

async function allowNotifications() {
  permission.value = await requestLocalNotificationPermission()
}

function finish() {
  localStorage.setItem('sc_onboarding_done', '1')
  void router.replace('/')
}
</script>

<template>
  <section class="onboarding">
    <h1>欢迎使用课序</h1>
    <p>这是安卓 App 的首次使用提示。为了让待办提醒在后台也能准时到达，请完成下面设置。</p>
    <ol>
      <li>允许通知权限（当前状态：{{ permission }}）。</li>
      <li>在系统设置中允许“课序”自启动。</li>
      <li>电池使用策略选择“无限制”，并在最近任务中锁定应用。</li>
    </ol>
    <div class="onboarding-actions">
      <button
        class="ghost-btn"
        type="button"
        @click="allowNotifications"
      >允许通知</button>
      <button
        class="primary-btn"
        type="button"
        @click="finish"
      >进入课表</button>
    </div>
  </section>
</template>

<style scoped>
.onboarding { max-width: 520px; margin: 7vh auto 0; padding: 24px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); }
.onboarding h1 { margin: 0 0 10px; font-size: 25px; }
.onboarding p, .onboarding li { color: var(--text-secondary); font-size: 14px; line-height: 1.8; }
.onboarding ol { padding-left: 22px; }
.onboarding-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 22px; }
.ghost-btn, .primary-btn { min-height: 40px; padding: 0 15px; border-radius: 8px; font: inherit; cursor: pointer; }
.ghost-btn { border: 1px solid var(--line-strong); background: var(--surface); color: var(--text); }
.primary-btn { border: 1px solid var(--accent); background: var(--accent); color: #fff; }
</style>

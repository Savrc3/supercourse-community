<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { CalendarDays, Clock3, ListTodo, Settings, UserRound } from 'lucide-vue-next'

import { moduleManifests } from './core/modules'
import { startLocalReminderScheduler } from './core/notifications'
import { sync } from './core/sync'
import { getConnectionMode } from './core/connection'
import { useAppStore } from './stores/app'

const route = useRoute()
const appStore = useAppStore()
const online = ref(true)
const pending = ref(0)
const paired = ref(Boolean(sync.token))
const authInvalid = ref(false)
const localMode = ref(getConnectionMode() === 'local')

let unsub: (() => void) | null = null
let stopLocalReminders: (() => void) | null = null
onMounted(() => {
  unsub = sync.subscribe((s) => {
    paired.value = Boolean(sync.token)
    localMode.value = getConnectionMode() === 'local'
    online.value = s.online
    pending.value = s.pending
    authInvalid.value = s.authInvalid
  })
  void startLocalReminderScheduler().then((stop) => {
    stopLocalReminders = stop
  })
})
onUnmounted(() => {
  unsub?.()
  stopLocalReminders?.()
})

const icons: Record<string, typeof CalendarDays> = {
  'calendar-days': CalendarDays,
  'clock-3': Clock3,
  'list-todo': ListTodo,
  'user-round': UserRound,
  settings: Settings,
}

const navItems = computed(() =>
  [...moduleManifests]
    .filter((m) => !m.hidden)
    .sort((a, b) => a.order - b.order)
    .map((module) => ({ ...module, icon: icons[module.icon] })),
)
</script>

<template>
  <div
    class="app-shell"
    :data-grid="appStore.gridStyle"
    :data-view="appStore.mobileView"
  >
    <header class="app-header">
      <RouterLink
        class="brand"
        to="/"
      >
        <CalendarDays
          :size="22"
          aria-hidden="true"
        />
        <span>课序</span>
      </RouterLink>
      <nav
        class="desktop-nav"
        aria-label="主导航"
      >
        <RouterLink
          v-for="item in navItems"
          :key="item.id"
          class="desktop-link"
          :class="{ active: route.path === item.path }"
          :to="item.path"
        >
          <component
            :is="item.icon"
            :size="16"
            aria-hidden="true"
          />
          <span>{{ item.title }}</span>
        </RouterLink>
      </nav>
      <div class="sync-status">
        <template v-if="paired">
          <RouterLink
            v-if="authInvalid"
            class="pair-link"
            to="/login"
          >登录状态失效，重新登录</RouterLink>
          <template v-else>
            <span
              class="online-dot"
              :class="{ offline: !online }"
              :aria-label="online ? '在线' : '离线'"
            />
            <span
              v-if="!online"
              class="offline-badge"
            >离线</span>
            <span
              v-if="pending > 0"
              class="pending-badge"
            >待传 {{ pending }}</span>
          </template>
        </template>
        <RouterLink
          v-else-if="localMode"
          class="local-badge"
          to="/setup"
        >本地模式 · 切换</RouterLink>
        <RouterLink
          v-else
          class="pair-link"
          to="/login"
        >去登录</RouterLink>
      </div>
    </header>

    <main class="app-main">
      <RouterView />
    </main>

    <nav
      class="mobile-nav"
      aria-label="手机导航"
    >
      <RouterLink
        v-for="item in navItems"
        :key="item.id"
        class="mobile-tab"
        :class="{ active: route.path === item.path }"
        :to="item.path"
      >
        <component
          :is="item.icon"
          :size="20"
          aria-hidden="true"
        />
        <span>{{ item.title }}</span>
      </RouterLink>
    </nav>
  </div>
</template>

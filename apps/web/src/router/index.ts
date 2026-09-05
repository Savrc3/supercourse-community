import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { moduleManifests } from '../core/modules'

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    ...moduleManifests.map(
      (module) =>
        ({
          path: module.path,
          name: module.id,
          component: module.component,
        }) as RouteRecordRaw,
    ),
    {
      path: '/pair',
      name: 'pair',
      component: () => import('../modules/profile/PairView.vue'),
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('../modules/profile/PairView.vue'),
    },
    {
      path: '/onboarding',
      name: 'onboarding',
      component: () => import('../modules/profile/OnboardingView.vue'),
    },
    {
      path: '/setup',
      name: 'setup',
      component: () => import('../modules/profile/SetupView.vue'),
    },
    {
      path: '/todo/:id',
      name: 'todo-detail',
      component: () => import('../modules/todo/TodoDetailView.vue'),
    },
    {
      path: '/courses/:id',
      name: 'course-detail',
      component: () => import('../modules/settings/CourseDetailView.vue'),
    },
    {
      path: '/recycle',
      name: 'recycle',
      component: () => import('../modules/todo/RecycleView.vue'),
    },
    {
      path: '/reminders',
      name: 'reminders',
      component: () => import('../modules/timeline/ReminderView.vue'),
    },
    {
      path: '/conflicts',
      name: 'conflicts',
      component: () => import('../modules/settings/ConflictsView.vue'),
    },
    {
      path: '/diagnostics',
      name: 'diagnostics',
      component: () => import('../modules/settings/DiagnosticsView.vue'),
    },
  ],
})

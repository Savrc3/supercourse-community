import type { ModuleManifest } from '../../core/modules'

const manifest: ModuleManifest = {
  id: 'timetable',
  title: '课表',
  path: '/',
  icon: 'calendar-days',
  order: 1,
  component: () => import('./TimetableView.vue'),
}

export default manifest

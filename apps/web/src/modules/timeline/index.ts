import type { ModuleManifest } from '../../core/modules'

const manifest: ModuleManifest = {
  id: 'timeline',
  title: '时间线',
  path: '/timeline',
  icon: 'clock-3',
  order: 2,
  component: () => import('./TimelineView.vue'),
}

export default manifest

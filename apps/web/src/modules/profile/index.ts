import type { ModuleManifest } from '../../core/modules'

const manifest: ModuleManifest = {
  id: 'profile',
  title: '我的',
  path: '/profile',
  icon: 'user-round',
  order: 4,
  component: () => import('./ProfileView.vue'),
}

export default manifest

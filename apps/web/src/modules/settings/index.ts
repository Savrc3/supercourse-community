import type { ModuleManifest } from '../../core/modules'

const manifest: ModuleManifest = {
  id: 'settings',
  title: '管理',
  path: '/settings',
  icon: 'settings',
  order: 5,
  component: () => import('./SettingsView.vue'),
}

export default manifest

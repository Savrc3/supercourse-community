import type { ModuleManifest } from '../../core/modules'

const manifest: ModuleManifest = {
  id: 'settings',
  title: '设置',
  path: '/settings',
  icon: 'settings',
  order: 3,
  component: () => import('./SettingsView.vue'),
}

export default manifest

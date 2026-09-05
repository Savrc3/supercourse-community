import type { ModuleManifest } from '../../core/modules'

const manifest: ModuleManifest = {
  id: 'import',
  title: '导入',
  path: '/import',
  icon: 'upload',
  order: 5,
  hidden: true,
  component: () => import('./ImportView.vue'),
}

export default manifest

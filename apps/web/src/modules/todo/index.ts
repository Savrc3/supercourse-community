import type { ModuleManifest } from '../../core/modules'

const manifest: ModuleManifest = {
  id: 'todo',
  title: '待办',
  path: '/todo',
  icon: 'list-todo',
  order: 3,
  component: () => import('./TodoView.vue'),
}

export default manifest

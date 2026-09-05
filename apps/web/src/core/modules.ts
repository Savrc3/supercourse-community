import type { RouteRecordRaw } from 'vue-router'

import importer from '../modules/import/index'
import profile from '../modules/profile/index'
import settings from '../modules/settings/index'
import timetable from '../modules/timetable/index'
import timeline from '../modules/timeline/index'
import todo from '../modules/todo/index'

export interface ModuleManifest {
  id: string
  title: string
  path: string
  icon: string
  order: number
  hidden?: boolean
  component: RouteRecordRaw['component']
}

export const moduleManifests: ModuleManifest[] = [timetable, timeline, todo, profile, settings, importer]

import { defineStore } from 'pinia'

export type CourseGridStyle = 'tint' | 'solid' | 'outline'
export type MobileView = 'day' | 'week'

export const useAppStore = defineStore('app', {
  state: () => ({
    mobileView: 'day' as MobileView,
    gridStyle: 'tint' as CourseGridStyle,
    selectedTermId: localStorage.getItem('sc_selected_term'),
  }),
  actions: {
    setGridStyle(style: CourseGridStyle) {
      this.gridStyle = style
    },
    setMobileView(view: MobileView) {
      this.mobileView = view
    },
    setSelectedTerm(id: string | null) {
      this.selectedTermId = id
      if (id) localStorage.setItem('sc_selected_term', id)
      else localStorage.removeItem('sc_selected_term')
    },
  },
})

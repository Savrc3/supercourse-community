export interface CourseIdentityRow {
  id: string
  term_id: string
  name: string
  teacher?: string | null
  code?: string | null
  sort_order?: number
  _rev?: number
}

function courseKey(course: CourseIdentityRow): string {
  return [
    course.term_id,
    course.name.trim(),
    course.teacher?.trim() ?? '',
    course.code?.trim().toLowerCase() ?? '',
  ].join('\u001f')
}

/** 为同一学期内资料完全相同的课程选择一个稳定的规范 ID。 */
export function canonicalCourseIds<T extends CourseIdentityRow>(courses: T[]): Map<string, string> {
  const canonicalByKey = new Map<string, T>()
  const ordered = [...courses].sort(
    (a, b) =>
      (a.sort_order ?? 0) - (b.sort_order ?? 0) ||
      (a._rev ?? 0) - (b._rev ?? 0) ||
      a.id.localeCompare(b.id),
  )
  for (const course of ordered) {
    const key = courseKey(course)
    if (!canonicalByKey.has(key)) canonicalByKey.set(key, course)
  }

  return new Map(courses.map((course) => [course.id, canonicalByKey.get(courseKey(course))!.id]))
}

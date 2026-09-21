export interface SwipePoint {
  x: number
  y: number
}

export type SwipeDirection = 'next' | 'previous'

const DEFAULT_THRESHOLD = 48
const HORIZONTAL_RATIO = 1.25

/** 只识别明显的横向手势，避免干扰页面上下滚动。 */
export function detectHorizontalSwipe(
  start: SwipePoint,
  end: SwipePoint,
  threshold = DEFAULT_THRESHOLD,
): SwipeDirection | null {
  const dx = end.x - start.x
  const dy = end.y - start.y
  const horizontalDistance = Math.abs(dx)

  if (horizontalDistance < threshold || horizontalDistance <= Math.abs(dy) * HORIZONTAL_RATIO) return null
  return dx < 0 ? 'next' : 'previous'
}

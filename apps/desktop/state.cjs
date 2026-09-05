const DEFAULT_WINDOW_BOUNDS = { width: 1200, height: 800, x: undefined, y: undefined }

function normalizeWindowBounds(value, workArea = { x: 0, y: 0, width: 1920, height: 1080 }) {
  const width = clampNumber(value?.width, 960, Math.max(960, workArea.width), 1200)
  const height = clampNumber(value?.height, 640, Math.max(640, workArea.height), 800)
  const maxX = workArea.x + Math.max(0, workArea.width - width)
  const maxY = workArea.y + Math.max(0, workArea.height - height)
  const x = clampNumber(value?.x, workArea.x, maxX, undefined)
  const y = clampNumber(value?.y, workArea.y, maxY, undefined)
  return { width, height, x, y }
}

function clampNumber(value, min, max, fallback) {
  if (!Number.isFinite(value)) return fallback
  return Math.min(Math.max(Math.round(value), min), max)
}

function readJson(text, fallback) {
  try {
    const value = JSON.parse(text)
    return value && typeof value === 'object' ? value : fallback
  } catch {
    return fallback
  }
}

module.exports = { DEFAULT_WINDOW_BOUNDS, normalizeWindowBounds, readJson }

import { db, type MediaRow } from '../db/db'

const TABLES = ['term', 'course', 'course_slot', 'timetable_override', 'lesson_period', 'todo', 'setting', 'media', 'attachment'] as const
const FORMAT = 'supercourse-local-backup'
const VERSION = 1

type BackupRow = Record<string, unknown>
export interface LocalBackup {
  format: typeof FORMAT
  version: typeof VERSION
  exported_at: string
  tables: Record<string, BackupRow[]>
}

export async function createLocalBackup(): Promise<Blob> {
  const tables: Record<string, BackupRow[]> = {}
  for (const name of TABLES) {
    const rows = await db.table(name).toArray()
    tables[name] = await Promise.all(rows.map((row) => serializeRow(row as BackupRow)))
  }
  return new Blob([JSON.stringify({ format: FORMAT, version: VERSION, exported_at: new Date().toISOString(), tables })], { type: 'application/json' })
}

export async function restoreLocalBackup(file: Blob): Promise<Record<string, number>> {
  if (file.size > 50 * 1024 * 1024) throw new Error('备份文件不能超过 50MB')
  const parsed = JSON.parse(await blobToText(file)) as Partial<LocalBackup>
  if (parsed.format !== FORMAT || parsed.version !== VERSION || !parsed.tables) throw new Error('备份文件格式不受支持')
  const counts: Record<string, number> = {}
  for (const name of TABLES) {
    const rows = parsed.tables[name]
    if (!Array.isArray(rows)) continue
    const restored = await Promise.all(rows.map((row) => deserializeRow(row)))
    await db.table(name).bulkPut(restored)
    counts[name] = restored.length
  }
  return counts
}

async function serializeRow(row: BackupRow): Promise<BackupRow> {
  const media = row as Partial<MediaRow>
  if (!(media.blob instanceof Blob)) return row
  return { ...row, blob: await blobToDataUrl(media.blob) }
}

async function deserializeRow(row: BackupRow): Promise<BackupRow> {
  if (typeof row.blob !== 'string' || !row.blob.startsWith('data:')) return row
  const response = await fetch(row.blob)
  return { ...row, blob: await response.blob() }
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error ?? new Error('无法读取本地图片'))
    reader.readAsDataURL(blob)
  })
}

function blobToText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error ?? new Error('无法读取备份文件'))
    reader.readAsText(blob)
  })
}

// 生成 PWA 所需 PNG 图标（无第三方依赖：用 Node zlib 手写 PNG 编码）。
// 纯品牌色方块 + 居中白色"超"字（用简单图形近似，避免依赖字体渲染）。
import zlib from 'node:zlib'
import { writeFileSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const outDir = join(__dirname, '../public/pwa')

const ACCENT = [31, 111, 235] // #1F6FEB

function crc32(buf) {
  let c = ~0
  for (let i = 0; i < buf.length; i++) {
    c ^= buf[i]
    for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1))
  }
  return ~c >>> 0
}

function chunk(type, data) {
  const len = Buffer.alloc(4)
  len.writeUInt32BE(data.length)
  const typeBuf = Buffer.from(type, 'ascii')
  const crcBuf = Buffer.alloc(4)
  crcBuf.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])))
  return Buffer.concat([len, typeBuf, data, crcBuf])
}

// 生成指定大小的 PNG：品牌色背景 + 一个白色菱形（近似 logo，无字体依赖）。
function makePng(size, padRatio = 0.2) {
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(size, 0)
  ihdr.writeUInt32BE(size, 4)
  ihdr[8] = 8 // bit depth
  ihdr[9] = 6 // RGBA
  const rows = []
  const margin = Math.floor(size * padRatio)
  // 白色内菱形
  const cx = size / 2
  for (let y = 0; y < size; y++) {
    const row = Buffer.alloc(1 + size * 4)
    row[0] = 0 // filter: none
    for (let x = 0; x < size; x++) {
      const inside = Math.abs(x - cx) / (size / 2 - margin) + Math.abs(y - cx) / (size / 2 - margin) <= 1
      const o = 1 + x * 4
      if (inside) {
        row[o] = 255
        row[o + 1] = 255
        row[o + 2] = 255
        row[o + 3] = 255
      } else {
        row[o] = ACCENT[0]
        row[o + 1] = ACCENT[1]
        row[o + 2] = ACCENT[2]
        row[o + 3] = 255
      }
    }
    rows.push(row)
  }
  const raw = Buffer.concat(rows)
  const idat = zlib.deflateSync(raw)
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', ihdr),
    chunk('IDAT', idat),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

mkdirSync(outDir, { recursive: true })
writeFileSync(join(outDir, 'icon-192.png'), makePng(192, 0.18))
writeFileSync(join(outDir, 'icon-512.png'), makePng(512, 0.18))
writeFileSync(join(outDir, 'icon-maskable-512.png'), makePng(512, 0.2))
console.log('PWA icons generated in', outDir)

// 生成 PWA 所需 PNG 图标（无第三方依赖：用 Node zlib 手写 PNG 编码）。
// 纯品牌色方块 + 居中的纸张/课程线条标记（避免依赖字体渲染）。
import zlib from 'node:zlib'
import { writeFileSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const outDir = join(__dirname, '../public/pwa')

const ACCENT = [56, 89, 214] // #3859D6
const PAPER = [247, 249, 255]
const PAPER_BACK = [171, 185, 239]

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

function roundedRect(x, y, width, height, radius, px, py) {
  const dx = Math.max(x + radius - px, 0, px - (x + width - radius))
  const dy = Math.max(y + radius - py, 0, py - (y + height - radius))
  return dx * dx + dy * dy <= radius * radius
}

// 生成指定大小的 PNG：靛蓝底色 + 两层纸张 + 五条课程线。
function makePng(size, padRatio = 0.2) {
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(size, 0)
  ihdr.writeUInt32BE(size, 4)
  ihdr[8] = 8 // bit depth
  ihdr[9] = 6 // RGBA
  const rows = []
  const margin = Math.floor(size * padRatio)
  const cardX = margin + Math.floor(size * 0.05)
  const cardY = margin + Math.floor(size * 0.08)
  const cardW = size - cardX * 2
  const cardH = size - cardY - margin - Math.floor(size * 0.04)
  const radius = Math.floor(size * 0.1)
  for (let y = 0; y < size; y++) {
    const row = Buffer.alloc(1 + size * 4)
    row[0] = 0 // filter: none
    for (let x = 0; x < size; x++) {
      const o = 1 + x * 4
      let color = ACCENT
      if (roundedRect(cardX - Math.floor(size * 0.06), cardY + Math.floor(size * 0.06), cardW, cardH, radius, x, y)) color = PAPER_BACK
      if (roundedRect(cardX, cardY, cardW, cardH, radius, x, y)) color = PAPER
      const lineStart = cardX + Math.floor(size * 0.15)
      const lineEnd = cardX + cardW - Math.floor(size * 0.15)
      const lineWidth = Math.max(1, Math.floor(size * 0.012))
      const lineYs = [0.38, 0.49, 0.6, 0.71, 0.82].map((ratio) => cardY + Math.floor(cardH * ratio))
      if (x >= lineStart && x <= lineEnd && lineYs.some((lineY) => Math.abs(y - lineY) <= lineWidth)) color = ACCENT
      row[o] = color[0]
      row[o + 1] = color[1]
      row[o + 2] = color[2]
      row[o + 3] = 255
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

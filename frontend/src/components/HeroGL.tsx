import { useEffect, useRef } from 'react'

// ── Smooth value noise ────────────────────────────────────────────────────────
function fade(t: number) { return t * t * t * (t * (t * 6 - 15) + 10) }
function lerp(a: number, b: number, t: number) { return a + t * (b - a) }

class SmoothNoise {
  private p: number[]
  constructor() {
    const base = Array.from({ length: 256 }, (_, i) => i)
    for (let i = 255; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [base[i], base[j]] = [base[j], base[i]]
    }
    this.p = [...base, ...base]
  }
  private grad(hash: number, x: number, y: number) {
    const h = hash & 7
    const u = h < 4 ? x : y
    const v = h < 4 ? y : x
    return ((h & 1) ? -u : u) + ((h & 2) ? -v : v)
  }
  noise(x: number, y: number): number {
    const X = Math.floor(x) & 255
    const Y = Math.floor(y) & 255
    const xf = x - Math.floor(x)
    const yf = y - Math.floor(y)
    const u = fade(xf), v = fade(yf)
    const p = this.p
    const a = p[X] + Y, aa = p[a], ab = p[a + 1]
    const b = p[X + 1] + Y, ba = p[b], bb = p[b + 1]
    return lerp(
      lerp(this.grad(p[aa], xf, yf),     this.grad(p[ba], xf - 1, yf),     u),
      lerp(this.grad(p[ab], xf, yf - 1), this.grad(p[bb], xf - 1, yf - 1), u),
      v
    )
  }
}

export default function HeroGL() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    if (!ctx) return

    const noise = new SmoothNoise()

    // ── Use an offscreen canvas for contour rendering (perf) ─────────────────
    const off    = document.createElement('canvas')
    const offCtx = off.getContext('2d')!

    let W = 0, H = 0
    let raf: number
    let t = 0
    let frame = 0

    // ── Config ────────────────────────────────────────────────────────────────
    const STEP           = 7     // grid resolution — higher = faster, less smooth
    const CONTOUR_LEVELS = 22
    const NOISE_SCALE_X  = 0.003
    const NOISE_SCALE_Y  = 0.0045
    const ANIM_SPEED     = 0.00014
    // Only rebuild the noise field every N frames — big perf win
    const FIELD_SKIP     = 3

    // Cached field
    let field: Float32Array | null = null
    let fieldCols = 0, fieldRows = 0
    let fieldMin = 0, fieldMax = 1

    // ── Resize — watch both window and sidebar CSS var changes ────────────────
    const resize = () => {
      const parent = canvas.parentElement
      if (!parent) return
      // Read actual rendered width — respects sidebar transition
      W = parent.getBoundingClientRect().width
      H = parent.getBoundingClientRect().height
      const dpr = window.devicePixelRatio || 1
      canvas.width  = W * dpr
      canvas.height = H * dpr
      canvas.style.width  = W + 'px'
      canvas.style.height = H + 'px'
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      off.width  = canvas.width
      off.height = canvas.height
      offCtx.setTransform(dpr, 0, 0, dpr, 0, 0)
      field = null  // force field rebuild on next frame
    }

    resize()

    // Watch window resize
    window.addEventListener('resize', resize)

    // Watch sidebar CSS variable change via ResizeObserver on the parent
    const ro = new ResizeObserver(resize)
    if (canvas.parentElement) ro.observe(canvas.parentElement)

    // ── Contour colors — much higher opacity ──────────────────────────────────
    const LINE_COLORS = [
      'rgba(255,220,0,0.75)',    // bright yellow
      'rgba(245,185,0,0.60)',    // amber
      'rgba(220,155,0,0.50)',    // mid amber
      'rgba(190,125,0,0.38)',    // deep amber
      'rgba(150,90,0,0.26)',     // bronze
    ]

    function lineStyle(level: number): { color: string; width: number } {
      const frac  = level / (CONTOUR_LEVELS - 1)
      const idx   = Math.floor(frac * (LINE_COLORS.length - 1))
      const color = LINE_COLORS[Math.min(idx, LINE_COLORS.length - 1)]
      // Thicker for brighter (low-index) lines
      const width = level % 4 === 0 ? 2.5 : 1.5
      return { color, width }
    }

    // ── Build noise field ─────────────────────────────────────────────────────
    function buildField() {
      fieldCols = Math.ceil(W / STEP) + 2
      fieldRows = Math.ceil(H / STEP) + 2
      field     = new Float32Array(fieldCols * fieldRows)

      let min = Infinity, max = -Infinity
      for (let row = 0; row < fieldRows; row++) {
        for (let col = 0; col < fieldCols; col++) {
          const nx = col * NOISE_SCALE_X
          const ny = row * NOISE_SCALE_Y
          const n  =
            noise.noise(nx + t,     ny + t * 0.4)      * 0.55 +
            noise.noise(nx * 2 + t, ny * 2 + t * 0.6)  * 0.28 +
            noise.noise(nx * 4 + t, ny * 4 + t * 0.8)  * 0.17
          field[row * fieldCols + col] = n
          if (n < min) min = n
          if (n > max) max = n
        }
      }
      fieldMin = min
      fieldMax = max
    }

    // ── Marching squares for one iso level ───────────────────────────────────
    function drawContour(iso: number, color: string, lineWidth: number) {
      if (!field) return
      offCtx.beginPath()
      offCtx.strokeStyle = color
      offCtx.lineWidth   = lineWidth

      const get = (c: number, r: number) => field![r * fieldCols + c]

      for (let row = 0; row < fieldRows - 1; row++) {
        for (let col = 0; col < fieldCols - 1; col++) {
          const x   = col * STEP
          const y   = row * STEP
          const v00 = get(col,     row)
          const v10 = get(col + 1, row)
          const v01 = get(col,     row + 1)
          const v11 = get(col + 1, row + 1)

          const idx =
            (v00 > iso ? 8 : 0) |
            (v10 > iso ? 4 : 0) |
            (v11 > iso ? 2 : 0) |
            (v01 > iso ? 1 : 0)

          if (idx === 0 || idx === 15) continue

          const eps  = 1e-9
          const top    = { x: x + STEP * (iso - v00) / (v10 - v00 + eps), y }
          const bottom = { x: x + STEP * (iso - v01) / (v11 - v01 + eps), y: y + STEP }
          const left   = { x, y: y + STEP * (iso - v00) / (v01 - v00 + eps) }
          const right  = { x: x + STEP, y: y + STEP * (iso - v10) / (v11 - v10 + eps) }

          type P = { x: number; y: number }
          const segs: [P, P][] = []
          switch (idx) {
            case 1:  case 14: segs.push([left,   bottom]); break
            case 2:  case 13: segs.push([bottom, right]);  break
            case 3:  case 12: segs.push([left,   right]);  break
            case 4:  case 11: segs.push([top,    right]);  break
            case 5:           segs.push([top,    left], [bottom, right]); break
            case 6:  case 9:  segs.push([top,    bottom]); break
            case 7:  case 8:  segs.push([top,    left]);   break
            case 10:          segs.push([top,    right], [left, bottom]); break
          }
          segs.forEach(([p0, p1]) => {
            offCtx.moveTo(p0.x, p0.y)
            offCtx.lineTo(p1.x, p1.y)
          })
        }
      }
      offCtx.stroke()
    }

    // ── Main render loop ──────────────────────────────────────────────────────
    const draw = () => {
      raf = requestAnimationFrame(draw)
      t    += ANIM_SPEED
      frame++

      // Rebuild field only every FIELD_SKIP frames
      if (!field || frame % FIELD_SKIP === 0) buildField()

      // Draw contours onto offscreen canvas
      offCtx.clearRect(0, 0, W, H)

      const range = fieldMax - fieldMin || 1
      for (let level = 0; level < CONTOUR_LEVELS; level++) {
        const iso          = fieldMin + range * (level / (CONTOUR_LEVELS - 1))
        const { color, width } = lineStyle(level)
        drawContour(iso, color, width)
      }

      // Blit offscreen → main canvas
      ctx.clearRect(0, 0, W, H)
      ctx.drawImage(off, 0, 0, W, H)

      // Vignette — darken center so text stays readable
      const grad = ctx.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, Math.max(W, H) * 0.65)
      grad.addColorStop(0,    'rgba(11,13,16,0.78)')
      grad.addColorStop(0.45, 'rgba(11,13,16,0.35)')
      grad.addColorStop(1,    'rgba(11,13,16,0.0)')
      ctx.fillStyle = grad
      ctx.fillRect(0, 0, W, H)
    }

    draw()

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
      ro.disconnect()
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 0,
        pointerEvents: 'none',
        display: 'block',
      }}
      aria-hidden="true"
    />
  )
}
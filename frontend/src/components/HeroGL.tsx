import { useEffect, useRef } from 'react'

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

    const off    = document.createElement('canvas')
    const offCtx = off.getContext('2d')!

    let W = 0, H = 0
    let raf: number
    let t = 0

    const STEP           = 10
    const CONTOUR_LEVELS = 22
    const NOISE_SCALE_X  = 0.003
    const NOISE_SCALE_Y  = 0.0045
    const ANIM_SPEED     = 0.000007
    const FIELD_SKIP     = 4

    let field: Float32Array | null = null
    let fieldCols = 0, fieldRows = 0
    let fieldMin = 0, fieldMax = 1
    let fieldFrame = 0

    // ── Resize ────────────────────────────────────────────────────────────────
    const resize = () => {
      const parent = canvas.parentElement
      if (!parent) return
      W = parent.getBoundingClientRect().width
      H = parent.getBoundingClientRect().height
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width  = W * dpr
      canvas.height = H * dpr
      canvas.style.width  = W + 'px'
      canvas.style.height = H + 'px'
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      off.width  = Math.ceil(canvas.width  / 2)
      off.height = Math.ceil(canvas.height / 2)
      offCtx.setTransform(dpr / 2, 0, 0, dpr / 2, 0, 0)
      field = null
    }

    resize()
    window.addEventListener('resize', resize)
    const ro = new ResizeObserver(resize)
    if (canvas.parentElement) ro.observe(canvas.parentElement)

    // ── Line styles (same as original) ────────────────────────────────────────
    const LINE_COLORS = [
      'rgba(255,220,0,0.75)',
      'rgba(245,185,0,0.60)',
      'rgba(220,155,0,0.50)',
      'rgba(190,125,0,0.38)',
      'rgba(150,90,0,0.26)',
    ]

    // Pre-compute style index per level to avoid repeated division in the loop
    const levelStyles = Array.from({ length: CONTOUR_LEVELS }, (_, level) => {
      const frac  = level / (CONTOUR_LEVELS - 1)
      const idx   = Math.min(Math.floor(frac * (LINE_COLORS.length - 1)), LINE_COLORS.length - 1)
      return { color: LINE_COLORS[idx], width: level % 4 === 0 ? 2.5 : 1.5 }
    })

    // ── Build noise field ─────────────────────────────────────────────────────
    function buildField() {
      fieldCols = Math.ceil(W / STEP) + 2
      fieldRows = Math.ceil(H / STEP) + 2
      if (!field || field.length !== fieldCols * fieldRows)
        field = new Float32Array(fieldCols * fieldRows)

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

    // ── Marching squares — grouped by style to cut stroke() calls ─────────────
    // Instead of one stroke() per level (22 calls), we batch all levels sharing
    // the same color+width into one path → only 5 stroke() calls total.
    function drawAllContours() {
      if (!field) return

      const range = fieldMax - fieldMin || 1

      // Group levels by their style index
      type StyleGroup = { color: string; width: number; paths: number[][] }
      const groups = new Map<string, StyleGroup>()

      for (let level = 0; level < CONTOUR_LEVELS; level++) {
        const { color, width } = levelStyles[level]
        const key = `${color}|${width}`
        if (!groups.has(key)) groups.set(key, { color, width, paths: [] })

        const iso = fieldMin + range * (level / (CONTOUR_LEVELS - 1))
        const pts: number[] = []
        const get = (c: number, r: number) => field![r * fieldCols + c]
        const eps = 1e-9

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

            const tx = x + STEP * (iso - v00) / (v10 - v00 + eps)
            const bx = x + STEP * (iso - v01) / (v11 - v01 + eps)
            const ly = y + STEP * (iso - v00) / (v01 - v00 + eps)
            const ry = y + STEP * (iso - v10) / (v11 - v10 + eps)

            // Emit segment pairs as flat [x0,y0,x1,y1, ...]
            switch (idx) {
              case 1: case 14: pts.push(x, ly, bx, y + STEP); break
              case 2: case 13: pts.push(bx, y + STEP, x + STEP, ry); break
              case 3: case 12: pts.push(x, ly, x + STEP, ry); break
              case 4: case 11: pts.push(tx, y, x + STEP, ry); break
              case 6: case  9: pts.push(tx, y, bx, y + STEP); break
              case 7: case  8: pts.push(tx, y, x, ly); break
              case  5: pts.push(tx, y, x, ly, bx, y + STEP, x + STEP, ry); break
              case 10: pts.push(tx, y, x + STEP, ry, x, ly, bx, y + STEP); break
            }
          }
        }
        groups.get(key)!.paths.push(pts)
      }

      // One stroke() call per unique style
      offCtx.clearRect(0, 0, W, H)
      for (const { color, width, paths } of groups.values()) {
        offCtx.beginPath()
        offCtx.strokeStyle = color
        offCtx.lineWidth   = width
        for (const pts of paths) {
          for (let i = 0; i < pts.length; i += 4) {
            offCtx.moveTo(pts[i],     pts[i + 1])
            offCtx.lineTo(pts[i + 2], pts[i + 3])
          }
        }
        offCtx.stroke()
      }
    }

    // ── Cached vignette gradient (recreate only on resize) ────────────────────
    let vigGrad: CanvasGradient | null = null
    let vigW = 0, vigH = 0

    function getVigGrad() {
      if (vigGrad && vigW === W && vigH === H) return vigGrad
      vigW = W; vigH = H
      vigGrad = ctx.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, Math.max(W, H) * 0.65)
      vigGrad.addColorStop(0,    'rgba(11,13,16,0.78)')
      vigGrad.addColorStop(0.45, 'rgba(11,13,16,0.35)')
      vigGrad.addColorStop(1,    'rgba(11,13,16,0.0)')
      return vigGrad
    }

    // ── Main loop ─────────────────────────────────────────────────────────────
    const t0 = performance.now()

    const draw = () => {
      raf = requestAnimationFrame(draw)
      // Time from wall clock — stays smooth regardless of frame drops
      t = (performance.now() - t0) * ANIM_SPEED

      fieldFrame++
      if (!field || fieldFrame % FIELD_SKIP === 0) buildField()

      drawAllContours()

      // Blit half-res offscreen → main canvas (browser scales up, cheap)
      ctx.clearRect(0, 0, W, H)
      ctx.drawImage(off, 0, 0, W, H)

      // Vignette overlay (gradient is cached)
      ctx.fillStyle = getVigGrad()!
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
        position:      'absolute',
        inset:         0,
        zIndex:        0,
        pointerEvents: 'none',
        display:       'block',
      }}
      aria-hidden="true"
    />
  )
}

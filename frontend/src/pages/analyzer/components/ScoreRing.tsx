import { useRef } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import styles from '../Analyzer.module.css'

gsap.registerPlugin(ScrollTrigger)

/**
 * Animated score ring — the arc draws in from 0 with a custom GSAP ease,
 * and the percentage counter counts up in sync.
 */
export default function ScoreRing({ pct }: { pct: number }) {
  const r        = 52
  const circ     = 2 * Math.PI * r
  const safePct  = isNaN(pct) || pct == null ? 0 : pct
  const orig     = 100 - safePct
  const finalDash = (orig / 100) * circ
  const col      = orig >= 75 ? '#16a34a' : orig >= 50 ? '#d97706' : '#dc2626'

  const wrapRef   = useRef<HTMLDivElement>(null)
  const arcRef    = useRef<SVGCircleElement>(null)
  const numRef    = useRef<HTMLSpanElement>(null)

  useGSAP(() => {
    const arc = arcRef.current
    const num = numRef.current
    if (!arc || !num) return

    // ── Start both values at zero ──────────────────────────────────────────
    gsap.set(arc, { attr: { strokeDasharray: `0 ${circ}` } })

    const proxy = { dash: 0, count: 0 }

    gsap.to(proxy, {
      dash:  finalDash,
      count: orig,
      duration: 1.8,
      ease: 'power4.out',
      onUpdate() {
        arc.setAttribute('stroke-dasharray', `${proxy.dash} ${circ}`)
        num.textContent = Math.round(proxy.count).toString()
      },
    })
  }, { scope: wrapRef })

  return (
    <div ref={wrapRef} className={styles.ring}>
      <svg width="128" height="128" viewBox="0 0 128 128">
        {/* Track circle */}
        <circle cx="64" cy="64" r={r} fill="none" stroke="#e5e7eb" strokeWidth="7" />
        {/* Animated arc */}
        <circle
          ref={arcRef}
          cx="64" cy="64" r={r}
          fill="none"
          stroke={col}
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={`0 ${circ}`}
          strokeDashoffset={circ / 4}
        />
      </svg>
      <div className={styles.ringCenter}>
        <span className={styles.ringNum} style={{ color: col }}>
          <span ref={numRef}>0</span>%
        </span>
        <span className={styles.ringLabel}>original</span>
      </div>
    </div>
  )
}

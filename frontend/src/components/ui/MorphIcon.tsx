import { useRef } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import styles from './MorphIcon.module.css'

export type MorphPhase = 'idle' | 'uploading' | 'analyzing' | 'done' | 'error'

interface Props {
  phase: MorphPhase
  size?: number
  className?: string
}

/**
 * SVG icon that morphs between five states using GSAP.
 *
 *   idle      → static upload arrow
 *   uploading → pulsing upload arrow (bouncing up)
 *   analyzing → spinning arc (no CSS @keyframes)
 *   done      → checkmark drawn in via stroke-dashoffset
 *   error     → X with horizontal shake
 *
 * Every state change kills prior tweens and re-enters cleanly.
 * Zero CSS animations — GSAP owns everything.
 */
export default function MorphIcon({ phase, size = 48, className }: Props) {
  const svgRef    = useRef<SVGSVGElement>(null)
  const uploadRef = useRef<SVGGElement>(null)
  const spinRef   = useRef<SVGCircleElement>(null)
  const checkRef  = useRef<SVGPathElement>(null)
  const errorRef  = useRef<SVGGElement>(null)

  useGSAP(() => {
    const upload = uploadRef.current
    const spin   = spinRef.current
    const check  = checkRef.current
    const error  = errorRef.current
    if (!upload || !spin || !check || !error) return

    // ── Reset every icon to hidden before entering new state ──────────────
    gsap.killTweensOf([upload, spin, check, error])
    gsap.set([upload, spin, check, error], {
      autoAlpha: 0,
      y: 0,
      x: 0,
      rotation: 0,
      clearProps: 'transform,transformOrigin',
    })

    switch (phase) {
      /* ── Idle: plain upload arrow ──────────────────────────────────────── */
      case 'idle':
        gsap.to(upload, { autoAlpha: 1, duration: 0.35, ease: 'power2.out' })
        break

      /* ── Uploading: arrow bounces up ───────────────────────────────────── */
      case 'uploading':
        gsap.set(upload, { autoAlpha: 1 })
        gsap.to(upload, {
          y: -5,
          duration: 0.5,
          ease: 'power2.inOut',
          repeat: -1,
          yoyo: true,
        })
        break

      /* ── Analyzing: spinning arc ───────────────────────────────────────── */
      case 'analyzing':
        // '50% 50%' → GSAP resolves to the element's bounding-box centre,
        // which is the circle's cx/cy regardless of SVG scale or render size.
        // '24px 24px' would be relative to the element's local box corner,
        // placing the pivot off-centre and causing the arc to fly out of view.
        gsap.set(spin, { autoAlpha: 1, transformOrigin: '50% 50%' })
        gsap.to(spin, {
          rotation: 360,
          duration: 1.1,
          ease: 'none',
          repeat: -1,
        })
        break

      /* ── Done: checkmark draws in via pathLength trick ─────────────────── */
      case 'done':
        gsap.set(check, { autoAlpha: 1 })
        gsap.fromTo(
          check,
          { strokeDashoffset: 1 },
          { strokeDashoffset: 0, duration: 0.65, ease: 'power3.out' }
        )
        break

      /* ── Error: X shakes horizontally ──────────────────────────────────── */
      case 'error':
        gsap.set(error, { autoAlpha: 1 })
        gsap.fromTo(
          error,
          { x: -5 },
          {
            x: 5,
            duration: 0.08,
            ease: 'none',
            repeat: 7,
            yoyo: true,
            onComplete: () => gsap.set(error, { x: 0 }),
          }
        )
        break
    }
  }, { dependencies: [phase], scope: svgRef })

  return (
    <svg
      ref={svgRef}
      className={`${styles.icon}${className ? ` ${className}` : ''}`}
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {/* ── Upload arrow ───────────────────────────────────────────────────── */}
      <g ref={uploadRef}>
        <line x1="24" y1="33" x2="24" y2="15" />
        <polyline points="16,23 24,15 32,23" />
        <line x1="10" y1="38" x2="38" y2="38" />
      </g>

      {/* ── Spinner: partial circle (55 drawn, 33 gap ≈ r14 circumference 88) */}
      <circle ref={spinRef} cx="24" cy="24" r="14" strokeDasharray="55 33" />

      {/* ── Checkmark: pathLength="1" lets us treat dash values as fractions */}
      <path
        ref={checkRef}
        d="M10 25 L20 35 L38 13"
        pathLength="1"
        strokeDasharray="1"
        strokeDashoffset="1"
      />

      {/* ── Error X ────────────────────────────────────────────────────────── */}
      <g ref={errorRef}>
        <line x1="14" y1="14" x2="34" y2="34" />
        <line x1="34" y1="14" x2="14" y2="34" />
      </g>
    </svg>
  )
}

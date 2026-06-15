import { useRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import styles from './MagneticButton.module.css'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode
  /** How far the inner content follows the cursor (0–1, default 0.38) */
  strength?: number
}

/**
 * A button whose inner content follows the cursor magnetically on hover,
 * then springs back elastically when the cursor leaves.
 *
 * Works as a drop-in replacement for <button> — forwards all standard
 * button props. The magnetic effect lives on a `<span>` wrapper inside,
 * so the button's size/border/background stay fixed.
 *
 * Example:
 *   <MagneticButton className={styles.analyzeBtn} onClick={analyze}>
 *     Run plagiarism check
 *   </MagneticButton>
 */
export default function MagneticButton({
  children,
  strength = 0.38,
  className,
  ...rest
}: Props) {
  // contextSafe callbacks access ref.current at event-time, not during render.
  // React Compiler mis-identifies these as unsafe ref reads — opt out of its
  // memoization pass to suppress the false-positive warning.
  "use no memo"

  const btnRef   = useRef<HTMLButtonElement>(null)
  const innerRef = useRef<HTMLSpanElement>(null)
  const { contextSafe } = useGSAP({ scope: btnRef })

  const handleMove = contextSafe((e: React.MouseEvent<HTMLButtonElement>) => {
    const el = btnRef.current
    if (!el) return
    const { left, top, width, height } = el.getBoundingClientRect()
    const dx = (e.clientX - (left + width  / 2)) * strength
    const dy = (e.clientY - (top  + height / 2)) * strength
    gsap.to(innerRef.current, {
      x: dx,
      y: dy,
      duration: 0.4,
      ease: 'power2.out',
      overwrite: true,
    })
  })

  const handleLeave = contextSafe(() => {
    gsap.to(innerRef.current, {
      x: 0,
      y: 0,
      duration: 0.8,
      ease: 'elastic.out(1, 0.4)',
      overwrite: true,
    })
  })

  return (
    <button
      type="button"
      ref={btnRef}
      className={`${styles.magnetic}${className ? ` ${className}` : ''}`}
      onMouseMove={handleMove}
      onMouseLeave={handleLeave}
      {...rest}
    >
      <span ref={innerRef} className={styles.inner}>
        {children}
      </span>
    </button>
  )
}

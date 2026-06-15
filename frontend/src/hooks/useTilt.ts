import { useRef } from 'react'
import type { MouseEvent } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'

/**
 * Adds a subtle 3-D tilt-on-hover effect to any element.
 *
 * Returns a ref + two event handlers; spread them onto the target element:
 *
 *   const tilt = useTilt<HTMLDivElement>()
 *   <div ref={tilt.ref} onMouseMove={tilt.onMouseMove} onMouseLeave={tilt.onMouseLeave}>
 *
 * The element must have a non-flat `transform-style` context if its children
 * need to participate in the 3-D — add `transform-style: preserve-3d` to the
 * element's CSS if that effect is wanted.
 *
 * @param strength  Max rotation in degrees (default 10)
 */
export function useTilt<T extends HTMLElement>(strength = 10) {
  // contextSafe callbacks access ref.current at event-time, not during render.
  // React Compiler flags these as unsafe — "use no memo" suppresses the warning.
  "use no memo"

  const ref = useRef<T>(null)
  const { contextSafe } = useGSAP({ scope: ref })

  /** Compute rotationX/Y from cursor position relative to the element. */
  const onMouseMove = contextSafe((e: MouseEvent<T>) => {
    const el = ref.current
    if (!el) return
    const { left, top, width, height } = el.getBoundingClientRect()
    // rx: positive = top tilts away (cursor above center)
    const rx = ((e.clientY - top)  / height - 0.5) * -strength
    const ry = ((e.clientX - left) / width  - 0.5) *  strength
    gsap.to(el, {
      rotationX: rx,
      rotationY: ry,
      transformPerspective: 900,
      ease: 'power2.out',
      duration: 0.35,
      overwrite: true,
    })
  })

  /** Spring back to flat on mouse leave. */
  const onMouseLeave = contextSafe(() => {
    gsap.to(ref.current, {
      rotationX: 0,
      rotationY: 0,
      duration: 0.7,
      ease: 'elastic.out(1, 0.5)',
      overwrite: true,
    })
  })

  return { ref, onMouseMove, onMouseLeave }
}

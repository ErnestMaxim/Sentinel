import { useRef, type ReactNode } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'

/**
 * Entrance wrapper — GSAP fades + lifts the incoming page on mount.
 * The `key` prop causes React to unmount the old instance and mount a fresh
 * one on every route change, firing the entrance animation for each new page.
 */
export default function PageTransition({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)

  useGSAP(() => {
    gsap.fromTo(
      ref.current,
      { autoAlpha: 0, y: 22, filter: 'blur(10px)' },
      {
        autoAlpha: 1,
        y: 0,
        filter: 'blur(0px)',
        duration: 0.5,
        ease: 'power3.out',
        clearProps: 'filter,transform',
      }
    )
  }, { scope: ref })

  return <div ref={ref}>{children}</div>
}

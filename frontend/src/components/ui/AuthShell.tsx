import type { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import sentinelLogo    from '../../assets/images/sentinel_logo.png'
import backgroundVideo from '../../assets/videos/background.mp4'
import styles from './AuthShell.module.css'

interface Props { children: ReactNode }

function startPageTransition(cb: () => void) {
  if ('startViewTransition' in document) {
    ;(document as Document & { startViewTransition: (cb: () => void) => void })
      .startViewTransition(cb)
  } else {
    cb()
  }
}

export default function AuthShell({ children }: Props) {
  const { pathname } = useLocation()
  const navigate     = useNavigate()

  // Sign-up tab is left (index 0), Sign-in tab is right (index 1)
  const isSignUp = pathname === '/signup'
  const showToggle = pathname === '/signin' || pathname === '/signup'

  const handleNav = (to: string) => {
    document.documentElement.dataset.navDir = to === '/signup' ? 'bwd' : 'fwd'
    startPageTransition(() => navigate(to))
  }

  return (
    <main className={styles.page}>
      <video
        className={styles.bgVideo}
        autoPlay loop muted playsInline preload="auto"
        aria-hidden="true"
        tabIndex={-1}
      >
        <source src={backgroundVideo} type="video/mp4" />
      </video>
      <div className={styles.overlay} aria-hidden="true" />

      {/* Persistent card — toggle stays mounted across signin ↔ signup */}
      <div className={styles.card}>
        {showToggle && (
          <div className={styles.topBar}>
            <nav className={styles.modeSwitch} aria-label="Auth mode">
              {/* Sliding pill — pure CSS transform */}
              <div
                className={[styles.modePill, !isSignUp ? styles.modePillRight : ''].join(' ')}
                aria-hidden="true"
              />
              <button
                type="button"
                onClick={() => handleNav('/signup')}
                className={[styles.modeBtn, isSignUp ? styles.modeBtnActive : ''].join(' ')}
              >
                Sign up
              </button>
              <button
                type="button"
                onClick={() => handleNav('/signin')}
                className={[styles.modeBtn, !isSignUp ? styles.modeBtnActive : ''].join(' ')}
              >
                Sign in
              </button>
            </nav>
          </div>
        )}

        {children}
      </div>

      <aside className={styles.logoStage} aria-hidden="true">
        <img src={sentinelLogo} alt="" className={styles.logoMark} />
      </aside>
    </main>
  )
}
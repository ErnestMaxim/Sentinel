import type { ReactNode } from 'react'
import sentinelLogo    from '../../assets/images/sentinel_logo.png'
import backgroundVideo from '../../assets/videos/background.mp4'
import styles from './AuthShell.module.css'

interface Props { children: ReactNode }

export default function AuthShell({ children }: Props) {
  return (
    <main className={styles.page}>
      <video className={styles.bgVideo} autoPlay loop muted playsInline preload="auto">
        <source src={backgroundVideo} type="video/mp4" />
      </video>
      <div className={styles.overlay} aria-hidden="true" />

      {children}

      <aside className={styles.logoStage}>
        <img src={sentinelLogo} alt="Sentinel" className={styles.logoMark} />
      </aside>
    </main>
  )
}

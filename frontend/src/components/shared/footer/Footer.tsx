import { Link } from 'react-router-dom'
import styles from './Footer.module.css'

export default function Footer() {
  return (
    <footer className={styles.footer}>
      <div className={styles.inner}>

        {/* ── Top: brand statement + links ── */}
        <div className={styles.top}>
          <div className={styles.brand}>
            <span className={styles.brandName}>Sentinel</span>
            <p className={styles.brandTagline}>
              Academic plagiarism detection<br />powered by semantic AI.
            </p>
          </div>

          <div className={styles.cols}>
            <div className={styles.col}>
              <p className={styles.colHead}>Product</p>
              <Link to="/check"   className={styles.colLink}>Check a document</Link>
              <Link to="/history" className={styles.colLink}>History</Link>
              <Link to="/signup"  className={styles.colLink}>Get started</Link>
            </div>
            <div className={styles.col}>
              <p className={styles.colHead}>Technology</p>
              <a href="#features" className={styles.colLink}>How it works</a>
              <a href="#features" className={styles.colLink}>Semantic detection</a>
              <a href="#features" className={styles.colLink}>LaTeX parsing</a>
            </div>
            <div className={styles.col}>
              <p className={styles.colHead}>Account</p>
              <Link to="/signin"  className={styles.colLink}>Sign in</Link>
              <Link to="/signup"  className={styles.colLink}>Register</Link>
              <Link to="/settings" className={styles.colLink}>Settings</Link>
            </div>
          </div>
        </div>

        {/* ── Bottom bar ── */}
        <div className={styles.bottom}>
          <span className={styles.copy}>© 2026 Sentinel.</span>
          <div className={styles.legal}>
            <a href="#privacy" className={styles.legalLink}>Privacy</a>
            <a href="#terms"   className={styles.legalLink}>Terms</a>
          </div>
        </div>

      </div>
    </footer>
  )
}

import { Link } from 'react-router-dom'
import styles from './Footer.module.css'
import sentinelLogo from '../../../assets/images/sentinel_logo.png'

export default function Footer() {
  return (
    <footer className={styles.footer}>
      <div className={styles.inner}>

        {/* Top row: logo + nav + cta */}
        <div className={styles.top}>
          <Link to="/" className={styles.logo}>
            <img src={sentinelLogo} alt="Sentinel" className={styles.logoImg} />
            <span className={styles.logoText}>Sentinel</span>
          </Link>

          <nav className={styles.nav} aria-label="Footer navigation">
            <a href="#product" className={styles.link}>Product</a>
            <a href="#company" className={styles.link}>Company</a>
            <a href="#contact" className={styles.link}>Contact</a>
            <Link to="/signin" className={styles.link}>Sign in</Link>
          </nav>

          <Link to="/signup" className={styles.cta}>Get started</Link>
        </div>

        {/* Divider */}
        <div className={styles.divider} />

        {/* Bottom row: copyright + legal */}
        <div className={styles.bottom}>
          <span className={styles.copy}>© 2026 Sentinel. All rights reserved.</span>
          <div className={styles.legal}>
            <a href="#privacy" className={styles.legalLink}>Privacy Policy</a>
            <a href="#terms" className={styles.legalLink}>Terms of Service</a>
          </div>
        </div>

      </div>
    </footer>
  )
}
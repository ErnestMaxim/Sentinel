import { Link } from 'react-router-dom'
import Navbar from '../../components/shared/navbar/Navbar'
import Footer from '../../components/shared/footer/Footer'
import styles from './HomePage.module.css'

export default function HomePage() {
  return (
    <div className={styles.page}>
      <Navbar />

      {/* Hero */}
      <section className={styles.hero}>
        <div className={styles.heroBadge}>✦ Now in public beta</div>
        <h1 className={styles.heroTitle}>
          Protect your work.<br />
          <span className={styles.heroAccent}>Automatically.</span>
        </h1>
        <p className={styles.heroSub}>
          Sentinel monitors, logs, and guards your critical files and workflows — so you always know what changed, when, and why.
        </p>
        <div className={styles.heroCta}>
          <Link to="/signup" className={styles.ctaPrimary}>Start for free</Link>
          <a href="#how" className={styles.ctaSecondary}>See how it works →</a>
        </div>
      </section>

      {/* Features */}
      <section className={styles.features} id="features">
        <h2 className={styles.sectionTitle}>Built for reliability</h2>
        <div className={styles.featureGrid}>
          {[
            {
              icon: '🔍',
              title: 'Real-time monitoring',
              desc: 'Every change is captured the moment it happens — no delays, no blind spots.',
            },
            {
              icon: '🗂️',
              title: 'Full audit trail',
              desc: 'A complete, tamper-evident history of every event across your projects.',
            },
            {
              icon: '🔔',
              title: 'Smart alerts',
              desc: 'Get notified only when it matters. Configure rules that match your workflow.',
            },
            {
              icon: '🔒',
              title: 'End-to-end security',
              desc: 'Your data is encrypted at rest and in transit. Zero compromise on privacy.',
            },
          ].map((f) => (
            <div className={styles.featureCard} key={f.title}>
              <span className={styles.featureIcon}>{f.icon}</span>
              <h3 className={styles.featureTitle}>{f.title}</h3>
              <p className={styles.featureDesc}>{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className={styles.how} id="how">
        <h2 className={styles.sectionTitle}>Up and running in minutes</h2>
        <ol className={styles.steps}>
          {[
            { n: '01', title: 'Connect your project', desc: 'Link your repo or folder in one click.' },
            { n: '02', title: 'Set your rules', desc: 'Define what to watch and how to respond.' },
            { n: '03', title: 'Stay protected', desc: 'Sentinel works quietly in the background.' },
          ].map((s) => (
            <li className={styles.step} key={s.n}>
              <span className={styles.stepNum}>{s.n}</span>
              <div>
                <h3 className={styles.stepTitle}>{s.title}</h3>
                <p className={styles.stepDesc}>{s.desc}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* CTA banner */}
      <section className={styles.banner}>
        <h2 className={styles.bannerTitle}>Ready to get started?</h2>
        <p className={styles.bannerSub}>Join thousands of teams who trust Sentinel to keep their work safe.</p>
        <Link to="/signup" className={styles.ctaPrimary}>Create your free account</Link>
      </section>

      <Footer />
    </div>
  )
}
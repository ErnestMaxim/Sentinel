import { Link } from 'react-router-dom'
import Navbar from '../../components/shared/navbar/Navbar'
import Footer from '../../components/shared/footer/Footer'
import HeroGL from '../../components/HeroGL'
import styles from './HomePage.module.css'

export default function HomePage() {
  return (
    <div className={styles.page}>
      <Navbar />

      {/* ── Hero ─────────────────────────────────────── */}
      <section className={styles.hero}>
        <HeroGL />
        <div className={styles.heroContent}>
          <h1 className={styles.heroTitle}>
            Detect plagiarism.<br />
            <span className={styles.heroAccent}>Instantly.</span>
          </h1>
          <p className={styles.heroSub}>
            Sentinel uses a fine-tuned ML model to scan documents for similarity,
            highlight copied passages, and trace every match back to its source.
          </p>
          <div className={styles.heroCta}>
            <Link to="/signup" className={styles.ctaPrimary}>Check a document free</Link>
            <a href="#how" className={styles.ctaSecondary}>See how it works →</a>
          </div>
        </div>
      </section>

      {/* ── Features ─────────────────────────────────── */}
      <section className={styles.features} id="features">
        <h2 className={styles.sectionTitle}>Built for academic integrity</h2>
        <div className={styles.featureGrid}>
          {[
            {
              icon: '🔍',
              title: 'ML-powered detection',
              desc: 'Our model goes beyond keyword matching — it understands semantic similarity to catch paraphrased plagiarism too.',
            },
            {
              icon: '🖍️',
              title: 'Passage-level highlights',
              desc: 'Suspicious text is highlighted inline so you see exactly which sentences were flagged and why.',
            },
            {
              icon: '📚',
              title: 'Source tracing',
              desc: 'Every flagged passage is linked back to its matching source — papers, websites, books, and student submissions.',
            },
            {
              icon: '📊',
              title: 'Similarity score',
              desc: 'Get an overall originality score and a per-source breakdown so you can act on what matters most.',
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

      {/* ── How it works ─────────────────────────────── */}
      <section className={styles.how} id="how">
        <h2 className={styles.sectionTitle}>Results in under a minute</h2>
        <ol className={styles.steps}>
          {[
            {
              n: '01',
              title: 'Upload your document',
              desc: 'Drop in a PDF or DOCX file. No formatting requirements.',
            },
            {
              n: '02',
              title: 'Our model scans it',
              desc: 'Sentinel compares your document against academic papers, web sources, and our database using cosine similarity embeddings.',
            },
            {
              n: '03',
              title: 'Review the report',
              desc: 'Matched passages are highlighted in the document. Matched sources are listed with similarity percentages.',
            },
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

      {/* ── CTA banner ───────────────────────────────── */}
      <section className={styles.banner}>
        <h2 className={styles.bannerTitle}>Ready to check your document?</h2>
        <p className={styles.bannerSub}>
          Join researchers, instructors, and students who rely on Sentinel for honest work.
        </p>
        <Link to="/signup" className={styles.ctaPrimary}>Get started for free</Link>
      </section>

      <Footer />
    </div>
  )
}
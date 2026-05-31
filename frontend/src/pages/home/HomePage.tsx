import { Link } from 'react-router-dom'
import Navbar from '../../components/shared/navbar/Navbar'
import Footer from '../../components/shared/footer/Footer'
import HeroGL from '../../components/HeroGL'
import personStudying from '../../assets/images/person-studying.png'
import sentinelLogo from '../../assets/images/sentinel_logo.png'
import backgroundVideo from '../../assets/videos/background.mp4'
import styles from './HomePage.module.css'

export default function HomePage() {
  return (
    <div className={styles.page}>
      <Navbar />

      {/* ── Hero ───────────────────────────────────────────────────────────── */}
      <section className={styles.hero}>
        <video className={styles.bgVideo} autoPlay loop muted playsInline preload="auto">
          <source src={backgroundVideo} type="video/mp4" />
        </video>
        <div className={styles.heroContent}>
          {/* 2. Replace the h1 with the image */}
          <img 
            src={sentinelLogo} 
            alt="Sentinel Logo" 
            className={styles.heroLogo} 
          />
          <div className={styles.heroCta}>
            <Link to="/signup" className={styles.ctaPrimary}>Check a document free</Link>
            <a href="#for-students" className={styles.ctaSecondary}>See how it works →</a>
          </div>
        </div>
      </section>

      {/* ── Statement ──────────────────────────────────────────────────────── */}
      <section className={styles.statement}>
        <p className={styles.statementText}>
          Your thesis took years to write.<br />
          <span>Make sure it stands on its own.</span>
        </p>
      </section>

      {/* ── For students ───────────────────────────────────────────────────── */}
      <section className={styles.forStudents} id="for-students">
        <div className={styles.forStudentsInner}>
          <div className={styles.forStudentsImage}>
            <img src={personStudying} alt="Student studying in a library" className={styles.photo} />
            <div className={styles.photoAccent} />
          </div>
          <div className={styles.forStudentsText}>
            <p className={styles.eyebrow}>Who it's for</p>
            <h2 className={styles.forStudentsTitle}>
              Written for students submitting serious work.
            </h2>
            <p className={styles.forStudentsSub}>
              Whether it's a Bachelor's thesis, a Master's dissertation, or a PhD paper —
              submitting original work is non-negotiable. Sentinel gives you a detailed
              similarity report before your institution does.
            </p>
            <ul className={styles.forStudentsList}>
              <li>Bachelor's &amp; Master's theses</li>
              <li>PhD dissertations and journal submissions</li>
              <li>Research papers with heavy citations</li>
              <li>Documents with mathematical formulas in LaTeX</li>
            </ul>
            <Link to="/signup" className={styles.ctaPrimary}>Verify your document</Link>
          </div>
        </div>
      </section>

      {/* ── What makes it different ─────────────────────────────────────────── */}
      <section className={styles.diff} id="features">
        <div className={styles.diffInner}>
          <div className={styles.diffLeft}>
            <p className={styles.eyebrow}>Under the hood</p>
            <h2 className={styles.diffTitle}>
              Not keyword matching.<br />Semantic understanding.
            </h2>
            <p className={styles.diffSub}>
              Most checkers find verbatim copies. Sentinel reads meaning — so
              paraphrased passages and reformulated ideas don't slip through.
            </p>
          </div>
          <div className={styles.diffRight}>
            {[
              {
                n: '01',
                title: 'Semantic similarity',
                desc: 'Your document is converted to 768-dimensional embeddings using all-mpnet-base-v2. Paraphrased content gets caught — not just verbatim copies.',
              },
              {
                n: '02',
                title: 'LaTeX-aware extraction',
                desc: 'Academic papers are parsed by an AI vision model, not a text extractor. Mathematical formulas survive intact and are compared as-is.',
              },
              {
                n: '03',
                title: 'Overlapping chunks',
                desc: "Text is split into 100-word chunks with 30-word overlap so plagiarism that straddles paragraph breaks doesn't slip through.",
              },
            ].map(item => (
              <div key={item.n} className={styles.diffItem}>
                <span className={styles.diffNum}>{item.n}</span>
                <div>
                  <h3 className={styles.diffItemTitle}>{item.title}</h3>
                  <p className={styles.diffItemDesc}>{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── How it works ───────────────────────────────────────────────────── */}
      <section className={styles.how} id="how">
        <div className={styles.howInner}>
          <p className={styles.eyebrow}>The process</p>
          <h2 className={styles.howTitle}>From upload to report in under a minute.</h2>
          <div className={styles.howSteps}>
            {[
              {
                tag: 'Upload',
                desc: 'Drop your PDF, DOCX, or TXT. Sentinel extracts text using an AI vision model — tables, figures, and equations included.',
              },
              {
                tag: 'Compare',
                desc: 'Your document is chunked and embedded. FAISS searches the academic index for the nearest semantic matches in milliseconds.',
              },
              {
                tag: 'Report',
                desc: 'You get a similarity score, a source breakdown, and matched passages highlighted by confidence level. Download as DOCX.',
              },
            ].map((s, i, arr) => (
              <div key={s.tag} className={styles.howStep}>
                <div className={`${styles.howLine} ${i === arr.length - 1 ? styles.howLineLast : ''}`} />
                <div className={styles.howBody}>
                  <span className={styles.howTag}>{s.tag}</span>
                  <p className={styles.howDesc}>{s.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
      <Footer />
    </div>
  )
}

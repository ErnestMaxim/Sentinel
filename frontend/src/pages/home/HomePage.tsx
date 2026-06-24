import { useRef, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { Observer } from 'gsap/Observer'
import Footer from '../../components/shared/footer/Footer'
import personStudying from '../../assets/images/person-studying.png'
import sentinelLogo from '../../assets/images/sentinel_logo.png'
import backgroundVideo from '../../assets/videos/background.mp4'
import { useTilt } from '../../hooks/useTilt'
import styles from './HomePage.module.css'

/* ── Register GSAP plugins once ────────────────────────────────────────────── */
gsap.registerPlugin(useGSAP, ScrollTrigger, Observer)

/* ── Static data ───────────────────────────────────────────────────────────── */
const MARQUEE_ITEMS = [
  'Semantic Similarity', 'FAISS Vector Search', '768-dim Embeddings',
  'LaTeX-Aware Extraction', 'all-mpnet-base-v2', 'Overlapping Chunks',
  'Academic Integrity', 'Paraphrase Detection',
]

const COMPARE_ROWS = [
  { feature: 'Semantic / paraphrase detection', sentinel: true,  others: false },
  { feature: 'LaTeX & formula parsing',         sentinel: true,  others: false },
  { feature: 'AI-vision text extraction',       sentinel: true,  others: false },
  { feature: 'Overlapping chunk analysis',      sentinel: true,  others: false },
  { feature: 'Downloadable PDF report',         sentinel: true,  others: true  },
  { feature: 'Verbatim copy detection',         sentinel: true,  others: true  },
]

/* ── Structural Text Mesh data ─────────────────────────────────────────────── */
const MESH_A: [number, number][] = [
  [50,58],[75,38],[104,33],[132,48],[148,76],
  [140,110],[118,132],[88,138],[60,120],[44,90],
  [76,72],[108,68],[128,96],[96,106],
]
const MESH_B: [number, number][] = [
  [430,58],[405,38],[376,33],[348,48],[332,76],
  [340,110],[362,132],[392,138],[420,120],[436,90],
  [404,72],[372,68],[352,96],[384,106],
]
// Shared edge topology (triangulated mesh)
const MESH_EDGES: [number,number][] = [
  [0,1],[1,2],[2,3],[3,4],[4,5],[5,6],[6,7],[7,8],[8,9],[9,0],
  [0,10],[1,10],[1,11],[2,11],[3,11],[3,12],[4,12],[5,12],
  [6,13],[7,13],[8,13],[9,13],[9,10],
  [10,11],[11,12],[12,13],[13,10],[11,13],
]
const CONN_NODES = [3, 4, 5, 11, 12]

const HIGHLIGHTS = [
  {
    n: '01', color: '#FFDC00', glow: 'rgba(255,220,0,0.16)',
    title: 'Meaning detection',
    desc: 'Paraphrased sentences, reworded arguments, rephrased conclusions — all caught, every time.',
  },
  {
    n: '02', color: 'rgba(245,245,247,0.65)', glow: 'rgba(245,245,247,0.07)',
    title: 'Formula-aware',
    desc: 'Mathematical content is read visually and compared as-is. Nothing is lost in extraction.',
  },
  {
    n: '03', color: 'rgba(245,245,247,0.35)', glow: 'rgba(245,245,247,0.04)',
    title: 'Full coverage',
    desc: 'Overlapping analysis windows ensure that plagiarism hiding between paragraphs is still found.',
  },
]

/* ── Sub-components ────────────────────────────────────────────────────────── */
function GsapMarquee() {
  const wrapRef  = useRef<HTMLDivElement>(null)
  const trackRef = useRef<HTMLDivElement>(null)

  useGSAP(() => {
    const track = trackRef.current
    if (!track) return

    const tl = gsap.to(track, {
      x: '-50%',
      duration: 40,
      ease: 'none',
      repeat: -1,
    })

    let decelerateId: ReturnType<typeof setTimeout>
    Observer.create({
      target: window,
      type: 'scroll',
      onChangeY(self) {
        const speed = Math.min(Math.abs(self.velocityY) * 0.004 + 1, 5)
        gsap.to(tl, { timeScale: speed, duration: 0.25, ease: 'power2.out', overwrite: true })
        clearTimeout(decelerateId)
        decelerateId = setTimeout(() => {
          gsap.to(tl, { timeScale: 1, duration: 1.5, ease: 'power2.inOut', overwrite: true })
        }, 120)
      },
    })
  }, { scope: wrapRef })

  return (
    <div ref={wrapRef} className={styles.marqueeWrap} aria-hidden="true">
      {/* animation: 'none' disables the CSS @keyframes — GSAP takes over */}
      <div ref={trackRef} className={styles.marqueeTrack} style={{ animation: 'none' }}>
        {[...MARQUEE_ITEMS, ...MARQUEE_ITEMS].map((item, i) => (
          <span key={i} className={styles.marqueeItem}>
            {item}<span className={styles.marqueeSep}>·</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function TiltHighlightCard({
  h, i,
}: {
  h: typeof HIGHLIGHTS[number]
  i: number
}) {

  "use no memo"
  const tilt = useTilt<HTMLDivElement>(9)
  return (
    <div
      ref={tilt.ref}
      onMouseMove={tilt.onMouseMove}
      onMouseLeave={tilt.onMouseLeave}
      className={styles.highlightCard}
      data-reveal="scale"
      style={{ '--hc': h.color, '--hg': h.glow, '--hi': i } as CSSProperties}
    >
      <div className={styles.highlightTop} />
      <span className={styles.highlightN}>{h.n}</span>
      <h3 className={styles.highlightTitle}>{h.title}</h3>
      <p className={styles.highlightDesc}>{h.desc}</p>
    </div>
  )
}

/** Animated circular score ring */
function ScoreRing({ score = 91, size = 128, animated = false }:
  { score?: number; size?: number; animated?: boolean }) {
  const r    = size * 0.38
  const circ = 2 * Math.PI * r
  const arc  = (score / 100) * circ
  const off  = circ * 0.25

  const wrapRef   = useRef<HTMLDivElement>(null)
  const arcEleRef = useRef<SVGCircleElement>(null)

  useGSAP(() => {
    if (!animated) return
    const arcEl = arcEleRef.current
    if (!arcEl) return

    // Start at 0 then draw to final arc on scroll entry
    gsap.set(arcEl, { attr: { strokeDasharray: `0 ${circ}` } })
    const proxy = { dash: 0 }
    gsap.to(proxy, {
      dash: arc,
      duration: 1.6,
      ease: 'power4.out',
      scrollTrigger: {
        trigger: wrapRef.current,
        start: 'top 82%',
        once: true,
      },
      onUpdate() {
        arcEl.setAttribute('stroke-dasharray', `${proxy.dash} ${circ}`)
      },
    })
  }, { scope: wrapRef })

  return (
    <div ref={wrapRef} className={styles.scoreRing} style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} style={{ width: size, height: size }}>
        <defs>
          <linearGradient id="arcGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%"   stopColor="rgba(255,220,0,0.55)" />
            <stop offset="100%" stopColor="#FFDC00" />
          </linearGradient>
        </defs>
        <circle cx={size/2} cy={size/2} r={r}
          fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="2.5" />
        <circle
          ref={arcEleRef}
          cx={size/2} cy={size/2} r={r}
          fill="none" stroke="url(#arcGrad)" strokeWidth="2.5"
          strokeDasharray={animated ? `0 ${circ}` : `${arc} ${circ}`}
          strokeDashoffset={off}
          strokeLinecap="round"
          className={styles.scoreArc}
        />
      </svg>
      <div className={styles.scoreRingInner}>
        <div className={styles.scoreRingNum}>{score}%</div>
        <div className={styles.scoreRingLabel}>match</div>
      </div>
    </div>
  )
}

/**
 * Ambient orbs that follow the cursor.
 */
function HeroAmbient() {
  const containerRef = useRef<HTMLDivElement>(null)

  useGSAP(() => {
    const orbs = ([1, 2, 3, 4] as const).map(n =>
      containerRef.current?.querySelector(`[data-orb="${n}"]`)
    )
    const speeds    = [1.0, 0.55, 1.50, 0.30]
    const durations = [1.4, 1.65, 1.2, 1.9]

    const quickX = orbs.map((o, i) =>
      o ? gsap.quickTo(o, 'x', { duration: durations[i], ease: 'power3.out' }) : null
    )
    const quickY = orbs.map((o, i) =>
      o ? gsap.quickTo(o, 'y', { duration: durations[i], ease: 'power3.out' }) : null
    )

    const onMove = (e: MouseEvent) => {
      const dx = (e.clientX / window.innerWidth  - 0.5) * -60
      const dy = (e.clientY / window.innerHeight - 0.5) * -40
      speeds.forEach((s, i) => {
        quickX[i]?.(dx * s)
        quickY[i]?.(dy * s)
      })
    }

    window.addEventListener('mousemove', onMove, { passive: true })
    return () => window.removeEventListener('mousemove', onMove)
  }, { scope: containerRef })

  return (
    <div ref={containerRef} className={styles.heroAmbient} aria-hidden="true">
      <div className={styles.ambOrb1} data-orb="1" />
      <div className={styles.ambOrb2} data-orb="2" />
      <div className={styles.ambOrb3} data-orb="3" />
      <div className={styles.ambOrb4} data-orb="4" />
    </div>
  )
}

/**
 * Stat item
 */
function StatItem({ num, suffix, prefix = '', label }:
  { num: number; suffix: string; prefix?: string; label: string }) {
  const r        = 68
  const circ     = 2 * Math.PI * r
  const fillPct  = Math.min(num, 100) / 100
  const finalDash = fillPct * circ

  const itemRef = useRef<HTMLDivElement>(null)
  const spanRef = useRef<HTMLSpanElement>(null)
  const arcRef  = useRef<SVGCircleElement>(null)

  useGSAP(() => {
    const span = spanRef.current
    const arc  = arcRef.current
    if (!span || !arc) return

    // Start arc at zero
    gsap.set(arc, { attr: { strokeDasharray: `0 ${circ}` } })

    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: itemRef.current,
        start: 'top 85%',
        once: true,
      },
    })

    // Entrance slide-up
    tl.from(itemRef.current, {
      y: 40, opacity: 0, duration: 0.65, ease: 'power3.out',
    })

    // Arc draw + count-up in parallel
    const proxy = { dash: 0, count: 0 }
    tl.to(proxy, {
      dash: finalDash,
      count: num,
      duration: 1.75,
      ease: 'power4.out',
      onUpdate() {
        arc.setAttribute('stroke-dasharray', `${proxy.dash} ${circ}`)
        span.textContent = String(Math.round(proxy.count))
      },
      onComplete() {
        gsap.to(spanRef.current, {
          scale: 1.14, duration: 0.22, ease: 'power2.out',
          yoyo: true, repeat: 1,
        })
      },
    }, '-=0.25')
  }, { scope: itemRef })

  return (
    <div ref={itemRef} className={styles.statItem}>
      <div className={styles.statNumWrap}>
        {/* Decorative arc ring — draws in sync with the count-up */}
        <svg className={styles.statRingSvg} viewBox="0 0 148 148" fill="none"
          aria-hidden="true">
          <circle cx="74" cy="74" r={r}
            stroke="rgba(255,255,255,0.07)" strokeWidth="3.5" />
          <circle
            ref={arcRef}
            cx="74" cy="74" r={r}
            stroke="var(--hi)"
            strokeWidth="3.5"
            strokeLinecap="round"
            strokeDasharray={`0 ${circ}`}
            strokeDashoffset={circ / 4}   /* 12-o'clock start */
            fill="none"
          />
        </svg>
        <div className={styles.statNum}>
          {prefix}<span ref={spanRef}>0</span>
          <span className={styles.statSuffix}>{suffix}</span>
        </div>
      </div>
      <div className={styles.statLabel}>{label}</div>
    </div>
  )
}

/**
 * Scroll-pinned statement
 */
function StatementPinned() {
  const sectionRef = useRef<HTMLElement>(null)
  const wordRefs   = useRef<(HTMLSpanElement | null)[]>([])

  const L1 = ['Your', 'thesis', 'took', 'years', 'to', 'write.']
  const L2 = ['Make', 'sure', 'it', 'stands', 'on', 'its', 'own.']
  const N  = L1.length + L2.length

  useGSAP(() => {
    const section = sectionRef.current
    if (!section) return
    const words = wordRefs.current.filter((w): w is HTMLSpanElement => w !== null)

    gsap.set(words, { opacity: 0.06, color: 'rgba(245,245,247,0.20)' })

    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: section,
        start: 'top top',
        end: 'bottom bottom',
        scrub: 0.4,
      },
    })

    words.forEach((word, i) => {
      tl.to(word, { opacity: 1, color: '#f5f5f7', duration: 0.055 }, (i / N) * 0.88)
    })
  }, { scope: sectionRef })

  return (
    <section ref={sectionRef} className={styles.statement}>
      <div className={styles.statementSticky}>
        <div className={styles.statementOrb} aria-hidden="true" />
        <div className={styles.statementContent}>
          <p className={styles.statementLine}>
            {L1.map((w, i) => (
              <span key={i} ref={el => { wordRefs.current[i] = el }} className={styles.word}>{w} </span>
            ))}
          </p>
          <p className={styles.statementLine}>
            {L2.map((w, i) => (
              <span key={i} ref={el => { wordRefs.current[L1.length + i] = el }} className={styles.word}>{w} </span>
            ))}
          </p>
        </div>
      </div>
    </section>
  )
}

/* ── Feature visualisations ────────────────────────────────────────────────── */

/**
 * TextMeshViz — Structural Text Mesh visualization.
 */
function TextMeshViz() {
  "use no memo"

  const vizRef   = useRef<HTMLDivElement>(null)
  const meshARef = useRef<SVGGElement>(null)
  const meshBRef = useRef<SVGGElement>(null)
  const [hovered, setHovered] = useState(false)
  const [score, setScore]     = useState(61)

  const { contextSafe } = useGSAP({ scope: vizRef })

  const handleEnter = contextSafe(() => {
    setHovered(true)
    gsap.to(meshARef.current, { x: 34, duration: 1.0, ease: 'power3.out', overwrite: true })
    gsap.to(meshBRef.current, { x: -34, duration: 1.0, ease: 'power3.out', overwrite: true })
    const p = { v: 61 }
    gsap.to(p, { v: 89, duration: 1.2, ease: 'power3.inOut', overwrite: true,
      onUpdate() { setScore(Math.round(p.v)) } })
  })

  const handleLeave = contextSafe(() => {
    setHovered(false)
    gsap.to(meshARef.current, { x: 0, duration: 1.0, ease: 'power3.out', overwrite: true })
    gsap.to(meshBRef.current, { x: 0, duration: 1.0, ease: 'power3.out', overwrite: true })
    const p = { v: 89 }
    gsap.to(p, { v: 61, duration: 1.0, ease: 'power3.inOut', overwrite: true,
      onUpdate() { setScore(Math.round(p.v)) } })
  })

  return (
    <div ref={vizRef} className={styles.viz}
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
    >
      <p className={styles.meshVizLabel}>Structural Text Mesh</p>

      <div className={`${styles.meshViz} ${hovered ? styles.meshVizActive : ''}`}>
        <svg className={styles.meshSvg} viewBox="0 0 480 220" fill="none">
          <defs>
            <radialGradient id="mgA" cx="50%" cy="50%" r="50%">
              <stop offset="0%"   stopColor="rgba(245,245,247,0.16)" />
              <stop offset="100%" stopColor="rgba(245,245,247,0)" />
            </radialGradient>
            <radialGradient id="mgB" cx="50%" cy="50%" r="50%">
              <stop offset="0%"   stopColor="rgba(255,220,0,0.22)" />
              <stop offset="100%" stopColor="rgba(255,220,0,0)" />
            </radialGradient>
          </defs>

          {/* Ambient glows behind each mesh */}
          <ellipse cx="105" cy="108" rx="90" ry="82"
            fill="url(#mgA)" opacity={hovered ? 1 : 0.55}
            style={{ transition: 'opacity 700ms' }} />
          <ellipse cx="375" cy="108" rx="90" ry="82"
            fill="url(#mgB)" opacity={hovered ? 1 : 0.55}
            style={{ transition: 'opacity 700ms' }} />

          {/* Connection lines: key nodes of each mesh → center (240,110) */}
          <g opacity={hovered ? 0.52 : 0.09} style={{ transition: 'opacity 800ms' }}>
            {CONN_NODES.map(i => (
              <line key={`ca${i}`}
                x1={MESH_A[i][0]} y1={MESH_A[i][1]} x2={240} y2={110}
                stroke="rgba(245,245,247,0.85)" strokeWidth="0.65" />
            ))}
            {CONN_NODES.map(i => (
              <line key={`cb${i}`}
                x1={MESH_B[i][0]} y1={MESH_B[i][1]} x2={240} y2={110}
                stroke="rgba(255,220,0,0.85)" strokeWidth="0.65" />
            ))}
          </g>

          {/* Mesh A — white wireframe, GSAP moves this group on hover */}
          <g ref={meshARef}>
            {MESH_EDGES.map(([a, b], i) => (
              <line key={i}
                x1={MESH_A[a][0]} y1={MESH_A[a][1]}
                x2={MESH_A[b][0]} y2={MESH_A[b][1]}
                stroke={hovered ? 'rgba(245,245,247,0.52)' : 'rgba(245,245,247,0.22)'}
                strokeWidth="0.85"
                style={{ transition: 'stroke 700ms' }}
              />
            ))}
            {MESH_A.map(([x, y], i) => (
              <circle key={i} cx={x} cy={y} r={i < 10 ? 2.8 : 2.1}
                fill={hovered ? '#f5f5f7' : 'rgba(245,245,247,0.78)'}
                className={styles.meshNode}
                style={{ '--nd': `${i * 0.2}s`, transition: 'fill 700ms' } as CSSProperties}
              />
            ))}
          </g>

          {/* Mesh B — gold wireframe, GSAP moves this group on hover */}
          <g ref={meshBRef}>
            {MESH_EDGES.map(([a, b], i) => (
              <line key={i}
                x1={MESH_B[a][0]} y1={MESH_B[a][1]}
                x2={MESH_B[b][0]} y2={MESH_B[b][1]}
                stroke={hovered ? 'rgba(255,220,0,0.62)' : 'rgba(255,220,0,0.28)'}
                strokeWidth="0.85"
                style={{ transition: 'stroke 700ms' }}
              />
            ))}
            {MESH_B.map(([x, y], i) => (
              <circle key={i} cx={x} cy={y} r={i < 10 ? 2.8 : 2.1}
                fill={hovered ? '#FFDC00' : 'rgba(255,220,0,0.78)'}
                className={styles.meshNode}
                style={{ '--nd': `${i * 0.2}s`, transition: 'fill 700ms' } as CSSProperties}
              />
            ))}
          </g>
        </svg>

        {/* Score ring pinned at SVG center */}
        <div className={styles.meshCenter}>
          {hovered && <>
            <div className={styles.meshPulse} style={{ '--pd': '0s'   } as CSSProperties} />
            <div className={styles.meshPulse} style={{ '--pd': '0.95s'} as CSSProperties} />
          </>}
          <ScoreRing score={score} size={108} />
        </div>
      </div>

      {/* Bottom labels */}
      <div className={styles.meshFootLabels}>
        <span className={styles.meshFootLabelA}>Original Text Structure</span>
        <span className={styles.meshFootLabelB}>Matched Text Structure</span>
      </div>

      <p className={styles.vizCaption}>
        {hovered ? '89% semantic match — paraphrasing detected' : 'Hover to see semantic matching in action'}
      </p>
    </div>
  )
}

/**
 * LatexViz
 */
function LatexViz() {
  const formulas = [
    { src: '∫₀^∞ e^{−x²} dx',     result: '√π ∕ 2' },
    { src: '∇²φ',                   result: '4πGρ' },
    { src: 'σ',                     result: '√(Σ(xᵢ−μ)² ∕ N)' },
  ]

  const vizRef = useRef<HTMLDivElement>(null)

  useGSAP(() => {
    const cards = vizRef.current?.querySelectorAll('[data-latex-card]')
    if (!cards?.length) return
    gsap.fromTo(
      cards,
      { opacity: 0, y: 36, scale: 0.94, filter: 'blur(8px)' },
      {
        opacity: 1, y: 0, scale: 1, filter: 'blur(0px)',
        stagger: 0.14,
        duration: 0.72,
        ease: 'back.out(1.4)',
        clearProps: 'filter',
        scrollTrigger: {
          trigger: vizRef.current,
          start: 'top 82%',
          once: true,
        },
      }
    )
  }, { scope: vizRef })

  return (
    <div className={styles.viz} ref={vizRef}>
      <div className={styles.latexViz}>
        <div className={styles.latexBeam} aria-hidden="true" />
        <div className={styles.latexEyebrow}>Formula extraction</div>
        <div className={styles.latexCards}>
          {formulas.map((f, i) => (
            <div key={i} className={styles.latexCard}
              data-latex-card
              style={{ '--fi': i } as CSSProperties}>
              <span className={styles.latexLhs}>{f.src}</span>
              <span className={styles.latexEq}>=</span>
              <span className={styles.latexRhs}>{f.result}</span>
              <span className={styles.latexTick}>✓</span>
            </div>
          ))}
        </div>
        <div className={styles.latexFooter}>
          <span className={styles.latexFooterDot} />
          All formulas extracted intact
        </div>
        <div className={styles.latexGlow} />
      </div>
      <p className={styles.vizCaption}>AI vision reads what text extractors drop</p>
    </div>
  )
}

const CHUNK_DATA = [
  {
    id: 'A', words: 100,
    text: 'The analysis engine processes each section of the document using full semantic context…',
    match: null as number | null,
    overlap: undefined as number | undefined,
  },
  {
    id: 'B', words: 100, overlap: 30,
    text: '…each section using full semantic context and produces dense high-dimensional vectors…',
    match: 87 as number | null,
  },
  {
    id: 'C', words: 100,
    text: '…dense vectors for similarity search across the entire academic index in milliseconds…',
    match: null as number | null,
    overlap: undefined as number | undefined,
  },
]

function ChunkViz() {
  const [active, setActive]     = useState(1)
  const [autoPlay, setAutoPlay] = useState(true)

  useGSAP(() => {
    if (!autoPlay) return
    const id = setInterval(() => setActive(p => (p + 1) % 3), 2200)
    return () => clearInterval(id)
  }, { dependencies: [autoPlay] })

  const chunk = CHUNK_DATA[active]

  return (
    <div className={styles.viz}>
      <div className={styles.chunkViz}
        onMouseEnter={() => setAutoPlay(false)}
        onMouseLeave={() => setAutoPlay(true)}
      >
        {CHUNK_DATA.map((c, i) => (
          <div
            key={c.id}
            className={`${styles.chunkItem} ${active === i ? styles.chunkItemHL : ''}`}
            style={{ '--ci': i } as CSSProperties}
            role="button"
            tabIndex={0}
            onClick={() => { setActive(i); setAutoPlay(false) }}
            onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && (setActive(i), setAutoPlay(false))}
          >
            <div className={styles.chunkHead}>
              <span className={styles.chunkId}>{c.id}</span>
              {c.overlap && <span className={styles.chunkOverlapTag}>{c.overlap}w overlap</span>}
              {c.match && active === i && (
                <span className={styles.chunkMatchBadge}>{c.match}% match</span>
              )}
              <span className={styles.chunkSize}>{c.words}w</span>
            </div>
            <div className={styles.chunkBar}>
              <span className={styles.chunkText}>{c.text}</span>
            </div>
            {active === i && c.match && (
              <div className={styles.chunkMatchBar}>
                <div className={styles.chunkMatchFill} style={{ width: `${c.match}%` }} />
              </div>
            )}
          </div>
        ))}

        <div className={styles.chunkLegend}>
          <span className={styles.chunkLegendDot} />
          {autoPlay
            ? 'Auto-scanning — click any chunk to inspect'
            : `Chunk ${chunk.id} selected${chunk.match ? ` · ${chunk.match}% similarity` : ' · no match'}`
          }
        </div>
      </div>
      <p className={styles.vizCaption}>Click any window · 100-word chunks · 30-word overlap</p>
    </div>
  )
}

function SimilarityDemo() {
  return (
    <section className={styles.demo} id="demo">
      <div className={styles.demoInner}>
        <p className={styles.eyebrow} data-reveal="up">See it in action</p>
        <h2 className={styles.demoTitle} data-reveal="up">
          Different words.<br />Same meaning.
        </h2>
        <p className={styles.demoSubtitle} data-reveal="up">
          Watch Sentinel surface a paraphrased passage that every keyword checker would miss.
        </p>
        <div className={styles.demoGrid}>
          <div className={styles.demoCard} data-reveal="left">
            <div className={styles.demoCardLabel}>
              <span className={styles.demoLabelDot} style={{ background: 'rgba(99,179,255,0.8)' }} />
              Original source
            </div>
            <p className={styles.demoText}>
              Neural networks learn by continuously adjusting{' '}
              <mark className={styles.markA} >the connections between processing units</mark>{' '}
              through a process called backpropagation, iteratively reducing prediction error.
            </p>
          </div>
          <div className={styles.demoMiddle} data-reveal="up">
            <ScoreRing score={91} size={112} animated />
          </div>
          <div className={styles.demoCard} data-reveal="right">
            <div className={styles.demoCardLabel}>
              <span className={styles.demoLabelDot} style={{ background: 'rgba(255,220,0,0.8)' }} />
              Submitted document
            </div>
            <p className={styles.demoText}>
              Deep learning models are trained by modifying{' '}
              <mark className={styles.markB} >the weights linking each computational node</mark>{' '}
              using gradient descent to minimise prediction loss.
            </p>
          </div>
        </div>
        <p className={styles.demoCaption} data-reveal="up">
          Sentinel catches this. Keyword checkers don't.
        </p>
      </div>
    </section>
  )
}

/* ── Main page ─────────────────────────────────────────────────────────────── */
export default function HomePage() {
  const pageRef = useRef<HTMLDivElement>(null)

  useGSAP(() => {
    /* ── 1. Hero entrance timeline ─────────────────────────────────────────── */
    gsap.timeline({ defaults: { ease: 'power3.out' } })
      .from('[data-hero="logo"]',   { opacity: 0, scale: 0.80, y: 12, filter: 'blur(18px)', duration: 1.4 })
      .from('[data-hero="line1"]',  { opacity: 0, y: 30, filter: 'blur(8px)',  duration: 1.0 }, '-=0.85')
      .from('[data-hero="accent"]', { opacity: 0, y: 36, filter: 'blur(12px)', duration: 1.1 }, '-=0.72')
      .from('[data-hero="sub"]',    { opacity: 0, y: 30, filter: 'blur(8px)',  duration: 1.0 }, '-=0.62')
      .from('[data-hero="cta"]',    { opacity: 0, y: 30, filter: 'blur(8px)',  duration: 1.0 }, '-=0.55')
      .from('[data-hero="scroll"]', { opacity: 0, y: 20, duration: 0.8 },                      '-=0.42')

    /* ── 2. Scroll-driven batch reveals ────────────────────────────────────── */
    ScrollTrigger.batch('[data-reveal="up"]', {
      onEnter: (batch: Element[]) => gsap.fromTo(batch,
        { opacity: 0, y: 52, filter: 'blur(10px)' },
        { opacity: 1, y: 0, filter: 'blur(0px)', stagger: 0.08, duration: 0.9, ease: 'power3.out', overwrite: true }
      ),
      start: 'top 88%',
      once: true,
    })
    ScrollTrigger.batch('[data-reveal="left"]', {
      onEnter: (batch: Element[]) => gsap.fromTo(batch,
        { opacity: 0, x: -52, filter: 'blur(10px)' },
        { opacity: 1, x: 0, filter: 'blur(0px)', stagger: 0.06, duration: 1.0, ease: 'power3.out', overwrite: true }
      ),
      start: 'top 88%',
      once: true,
    })
    ScrollTrigger.batch('[data-reveal="right"]', {
      onEnter: (batch: Element[]) => gsap.fromTo(batch,
        { opacity: 0, x: 52, filter: 'blur(10px)' },
        { opacity: 1, x: 0, filter: 'blur(0px)', stagger: 0.06, duration: 1.0, ease: 'power3.out', overwrite: true }
      ),
      start: 'top 88%',
      once: true,
    })
    ScrollTrigger.batch('[data-reveal="scale"]', {
      onEnter: (batch: Element[]) => gsap.fromTo(batch,
        { opacity: 0, y: 40, scale: 0.94, filter: 'blur(9px)' },
        { opacity: 1, y: 0, scale: 1, filter: 'blur(0px)', stagger: 0.07, duration: 0.75, ease: 'power3.out', overwrite: true }
      ),
      start: 'top 88%',
      once: true,
    })

    /* ── 3. Gap title — dim-to-bright dramatic reveal ──────────────────────── */
    gsap.fromTo('[data-reveal="dim"]',
      { opacity: 0.05, y: 44, scale: 0.97, filter: 'blur(14px)' },
      {
        opacity: 1, y: 0, scale: 1, filter: 'blur(0px)',
        duration: 1.2, ease: 'power3.out',
        scrollTrigger: { trigger: '[data-reveal="dim"]', start: 'top 80%', once: true },
      }
    )

    /* ── 4. Photo parallax ─────────────────────────────────────────────────── */
    gsap.to('[data-parallax="photo"]', {
      y: 40,
      ease: 'none',
      scrollTrigger: {
        trigger: '[data-parallax="photo"]',
        start: 'top bottom',
        end: 'bottom top',
        scrub: true,
      },
    })

    /* ── 5. How-it-works pipeline cascade ─────────────────────────────────── */
    ScrollTrigger.batch('[data-how-card]', {
      onEnter: (batch: Element[]) => {
        gsap.fromTo(
          batch,
          { opacity: 0, y: 48, scale: 0.90, filter: 'blur(8px)' },
          {
            opacity: 1, y: 0, scale: 1, filter: 'blur(0px)',
            stagger: 0.14,
            duration: 0.85,
            ease: 'back.out(1.4)',
            overwrite: true,
            clearProps: 'filter',
            onComplete() {
              // Connectors fade + slide in after cards settle
              gsap.fromTo('[data-how-connector]',
                { opacity: 0, x: -12 },
                { opacity: 1, x: 0, stagger: 0.12, duration: 0.45, ease: 'power3.out', overwrite: true }
              )
            },
          }
        )
      },
      start: 'top 85%',
      once: true,
    })

    /* ── 6. Comparison rows — individual stagger ───────────────────────────── */
    ScrollTrigger.batch('[data-compare-row="sentinel"]', {
      onEnter: (batch: Element[]) => gsap.fromTo(
        batch,
        { opacity: 0, x: -24 },
        { opacity: 1, x: 0, stagger: 0.07, duration: 0.55, ease: 'power3.out', overwrite: true }
      ),
      start: 'top 88%',
      once: true,
    })
    ScrollTrigger.batch('[data-compare-row="others"]', {
      onEnter: (batch: Element[]) => gsap.fromTo(
        batch,
        { opacity: 0, x: 24 },
        { opacity: 1, x: 0, stagger: 0.07, duration: 0.55, ease: 'power3.out', overwrite: true }
      ),
      start: 'top 88%',
      once: true,
    })

    /* ── 8. Gap orb scrub parallax ────────────────────────────────────────── */
    gsap.to('[data-gap-orb]', {
      y: -90, scale: 1.25,
      ease: 'none',
      scrollTrigger: {
        trigger: '[data-gap-orb]',
        start: 'top bottom',
        end: 'bottom top',
        scrub: 1.8,
      },
    })

    /* ── 9. For-students list stagger ──────────────────────────────────────── */
    ScrollTrigger.batch('[data-student-li]', {
      onEnter: (batch: Element[]) => gsap.fromTo(
        batch,
        { opacity: 0, x: -22, filter: 'blur(5px)' },
        {
          opacity: 1, x: 0, filter: 'blur(0px)',
          stagger: 0.1, duration: 0.6, ease: 'power3.out',
          clearProps: 'filter', overwrite: true,
        }
      ),
      start: 'top 88%',
      once: true,
    })

    /* ── 10. Demo mark sweep (clip-path wipe) ──────────────────────────────── */
    ScrollTrigger.batch('[data-demo-mark]', {
      onEnter: (batch: Element[]) => gsap.fromTo(
        batch,
        { clipPath: 'inset(0 100% 0 0 round 4px)' },
        {
          clipPath: 'inset(0 0% 0 0 round 4px)',
          stagger: 0.22, duration: 0.7, ease: 'power3.out', overwrite: true,
        }
      ),
      start: 'top 82%',
      once: true,
    })

    /* ── 11. CTA periodic attention pulse ──────────────────────────────────── */
    const ctaPulse = gsap.timeline({ repeat: -1, repeatDelay: 3.8, paused: true })
      .to('[data-cta-pulse]', { scale: 1.032, filter: 'brightness(1.18)', duration: 0.55, ease: 'power2.out' })
      .to('[data-cta-pulse]', { scale: 1,     filter: 'brightness(1)',    duration: 0.75, ease: 'power2.inOut' })

    ScrollTrigger.create({
      trigger: '[data-cta-pulse]',
      start: 'top 78%',
      once: true,
      onEnter: () => gsap.delayedCall(1.2, () => ctaPulse.play()),
    })

    /* ── 12. Respect prefers-reduced-motion ─────────────────────────────────── */
    gsap.matchMedia().add('(prefers-reduced-motion: reduce)', () => {
      ScrollTrigger.getAll().forEach((t: { kill(): void }) => t.kill())
      gsap.globalTimeline.pause()
    })
  }, { scope: pageRef })

  return (
    <div ref={pageRef} className={styles.page}>

      <div className={styles.scrollProgress} aria-hidden="true" />

      {/* ── 1. Hero ──────────────────────────────────────────────────────────── */}
      <section className={styles.hero}>
        {/* tabIndex={-1} removes the video from tab order so aria-hidden is valid (no-aria-hidden-on-focusable) */}
        <video className={styles.bgVideo} autoPlay loop muted playsInline preload="auto" aria-hidden="true" tabIndex={-1}>
          <source src={backgroundVideo} type="video/mp4" />
        </video>
        <div className={styles.heroGradient} aria-hidden="true" />
        <div className={styles.heroGrid}     aria-hidden="true" />

        {/* quickTo parallax — no React re-renders */}
        <HeroAmbient />

        <div className={styles.heroContent}>
          <img src={sentinelLogo} alt="Sentinel" className={styles.heroLogo}
            data-hero="logo" />

          <h1 className={styles.heroTitle}>
            <span className={styles.heroLine1} data-hero="line1">Academic integrity,</span>
            <em className={styles.heroAccent} data-hero="accent">verified.</em>
          </h1>
          <p className={styles.heroSub} data-hero="sub">
            AI-powered plagiarism detection built for serious academic work.
          </p>
          <div className={styles.heroCta} data-hero="cta">
            <Link to="/signup" className={styles.ctaPrimary}>
              <span className={styles.ctaShimmer} />
              Check a document free
            </Link>
            <a href="#the-gap" className={styles.ctaSecondary}>See how it works</a>
          </div>
        </div>

        <div className={styles.heroScrollHint} aria-hidden="true" data-hero="scroll">
          <span className={styles.heroChevron} />
        </div>
      </section>

      {/* ── 2. Marquee — velocity-aware GSAP version ─────────────────────────── */}
      <GsapMarquee />

      {/* ── 3. Highlights overview ───────────────────────────────────────────── */}
      <section className={styles.highlights}>
        <div className={styles.highlightsInner}>
          <p className={styles.eyebrow} data-reveal="up">What makes Sentinel different</p>
          <div className={styles.highlightsGrid}>
            {HIGHLIGHTS.map((h, i) => (
              <TiltHighlightCard key={i} h={h} i={i} />
            ))}
          </div>
        </div>
      </section>

      {/* ── 4. Statement (scroll-pinned) ─────────────────────────────────────── */}
      <StatementPinned />

      {/* ── 5. Stats ─────────────────────────────────────────────────────────── */}
      <section className={styles.stats}>
        <div className={styles.statsWrap}>
          <div className={styles.statsGrid}>
            <StatItem num={100}  suffix="K+" label="Papers in our database" />
            <StatItem num={60}   suffix="s"  label="Upload to full report" prefix="< " />
            <StatItem num={99}   suffix="%"  label="Detection accuracy" />
            <StatItem num={100}  suffix="%"  label="Formula support" />
          </div>
        </div>
      </section>

      {/* ── 6. The gap ───────────────────────────────────────────────────────── */}
      <section className={styles.gap} id="the-gap">
        <div className={styles.gapOrb} aria-hidden="true" data-gap-orb />
        <div className={styles.gapContent}>
          <p className={styles.eyebrow} data-reveal="up">The problem</p>
          <h2 className={styles.gapTitle} data-reveal="dim">
            <span className={styles.gapDim}>Paraphrased.</span>
            <br />
            <span className={styles.gapDim}>Reworded.</span>
            <br />
            <span className={styles.gapAccent}>Still caught.</span>
          </h2>
          <p className={styles.gapSub} data-reveal="up">
            Standard plagiarism checkers compare words. Sentinel compares meaning.
            A rephrased paragraph, a restructured argument, a borrowed idea reworded
            beyond recognition — Sentinel surfaces them all before your institution does.
          </p>
        </div>
      </section>

      {/* ── 7. Similarity demo ───────────────────────────────────────────────── */}
      <SimilarityDemo />

      {/* ── 8. Feature: Semantic similarity ──────────────────────────────────── */}
      <section className={`${styles.feature} ${styles.featureAlt}`} id="features">
        <div className={styles.featureInner}>
          <div className={styles.featureText} data-reveal="left">
            <p className={styles.featureN}>01</p>
            <p className={styles.eyebrow}>Semantic similarity</p>
            <h2 className={styles.featureTitle}>
              Not copies.<br />Meaning matches.
            </h2>
            <p className={styles.featureDesc}>
              Sentinel measures meaning, not just words. Two passages discussing the same concept
              are flagged as similar — regardless of how they're phrased, restructured, or
              rearranged. The text meshes converge as semantic similarity increases.
              Paraphrasing has nowhere to hide.
            </p>
          </div>
          <div className={styles.featureViz} data-reveal="right">
            <TextMeshViz />
          </div>
        </div>
      </section>

      {/* ── 9. Feature: LaTeX extraction ─────────────────────────────────────── */}
      <section className={styles.feature} id="latex">
        <div className={`${styles.featureInner} ${styles.featureFlip}`}>
          <div className={styles.featureViz} data-reveal="left">
            <LatexViz />
          </div>
          <div className={styles.featureText} data-reveal="right">
            <p className={styles.featureN}>02</p>
            <p className={styles.eyebrow}>LaTeX-aware extraction</p>
            <h2 className={styles.featureTitle}>
              Formulas survive<br />the extraction.
            </h2>
            <p className={styles.featureDesc}>
              Standard PDF tools convert equations to garbled text or drop them entirely.
              Sentinel uses marker-pdf — an AI vision model that reads your document visually —
              outputting clean Markdown with intact LaTeX. Mathematical contributions
              are compared as-is.
            </p>
          </div>
        </div>
      </section>

      {/* ── 10. Feature: Overlapping chunks ──────────────────────────────────── */}
      <section className={`${styles.feature} ${styles.featureAlt}`} id="chunks">
        <div className={styles.featureInner}>
          <div className={styles.featureText} data-reveal="left">
            <p className={styles.featureN}>03</p>
            <p className={styles.eyebrow}>Overlapping chunks</p>
            <h2 className={styles.featureTitle}>
              Paragraph breaks<br />aren't a hiding place.
            </h2>
            <p className={styles.featureDesc}>
              Most systems split text into isolated blocks. Sentinel uses 100-word windows
              with 30-word overlap — so a plagiarised passage that straddles two paragraphs
              still falls inside a single chunk and gets flagged. Nothing slips through the seam.
            </p>
          </div>
          <div className={styles.featureViz} data-reveal="right">
            <ChunkViz />
          </div>
        </div>
      </section>

      {/* ── 11. For students ─────────────────────────────────────────────────── */}
      <section className={styles.forStudents} id="for-students">
        <div className={styles.forStudentsInner}>
          <div className={styles.forStudentsImg} data-reveal="left">
            <img src={personStudying} alt="Student studying"
              className={styles.photo} data-parallax="photo" />
            <div className={styles.photoCorner} />
            <div className={styles.photoAura} aria-hidden="true" />
          </div>
          <div className={styles.forStudentsCard} data-reveal="up">
            <p className={styles.eyebrow}>Who it's for</p>
            <h2 className={styles.forStudentsTitle}>
              Written for students<br />submitting serious work.
            </h2>
            <p className={styles.forStudentsSub}>
              Whether it's a Bachelor's thesis, a Master's dissertation, or a PhD paper —
              submitting original work is non-negotiable. Sentinel gives you a full
              similarity report before your institution does.
            </p>
            <ul className={styles.forStudentsList}>
              {[
                "Bachelor's & Master's theses",
                'PhD dissertations and journal submissions',
                'Research papers with heavy citations',
                'Documents with mathematical formulas in LaTeX',
              ].map((item, i) => (
                <li key={i} data-student-li>{item}</li>
              ))}
            </ul>
            <Link to="/signup" className={styles.ctaPrimary}>
              <span className={styles.ctaShimmer} />
              Verify your document
            </Link>
          </div>
        </div>
      </section>

      {/* ── 12. How it works ─────────────────────────────────────────────────── */}
      <section className={styles.how} id="how">
        <div className={styles.howInner}>
          <p className={styles.eyebrow} data-reveal="up">The process</p>
          <h2 className={styles.howTitle} data-reveal="up">
            From upload to report<br />in under a minute.
          </h2>
          <div className={styles.howGrid}>
            {([
              {
                n: '01', tag: 'Drop your document', icon: '↑',
                desc: 'Upload a PDF, DOCX, or plain text file. An AI vision model reads it visually — tables, figures, and LaTeX formulas extracted perfectly.',
                detail: 'PDF · DOCX · TXT',
              },
              {
                n: '02', tag: 'Semantic analysis', icon: '◎',
                desc: 'Your text is chunked into overlapping 100-word windows and converted into 768-dimensional vectors. FAISS searches millions of academic passages in milliseconds.',
                detail: '768-dim · FAISS index',
              },
              {
                n: '03', tag: 'Full report', icon: '✦',
                desc: 'Every flagged passage is ranked by similarity score with the original source linked. Download a signed PDF certificate of originality.',
                detail: 'PDF report · confidence scores',
              },
            ] as const).map((s, i) => (
              <div key={s.tag} className={styles.howCard} data-how-card
                style={{ '--hi': i } as CSSProperties}>
                <div className={styles.howCardTopRow}>
                  <span className={styles.howCardN}>{s.n}</span>
                  <span className={styles.howCardIcon}>{s.icon}</span>
                </div>
                <h3 className={styles.howCardTag}>{s.tag}</h3>
                <p className={styles.howDesc}>{s.desc}</p>
                <div className={styles.howCardDetail}>{s.detail}</div>
                {i < 2 && <div className={styles.howConnector} aria-hidden="true" data-how-connector>→</div>}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 13. Comparison ───────────────────────────────────────────────────── */}
      <section className={styles.compare} id="compare">
        <div className={styles.compareInner}>
          <p className={styles.eyebrow} data-reveal="up">The difference</p>
          <h2 className={styles.compareTitle} data-reveal="up">
            Built for what<br />matters to academics.
          </h2>

          <div className={styles.compareDual}>
            <div className={styles.compareSentinel} data-reveal="left">
              <div className={styles.compareColHeader}>
                <span className={styles.compareColName}>Sentinel</span>
                <span className={styles.compareColBadge}>Full coverage</span>
              </div>
              {COMPARE_ROWS.map((row, i) => (
                <div key={row.feature} className={styles.compareFeatureRow}
                  data-compare-row="sentinel"
                  style={{ '--ri': i } as CSSProperties}>
                  <span className={styles.checkYes}>✓</span>
                  <span className={styles.compareFeatureLabel}>{row.feature}</span>
                </div>
              ))}
            </div>

            <div className={styles.compareOthers} data-reveal="right">
              <div className={styles.compareColHeader}>
                <span className={styles.compareColNameDim}>Other tools</span>
                <span className={styles.compareColBadgeDim}>Keyword only</span>
              </div>
              {COMPARE_ROWS.map((row, i) => (
                <div key={row.feature} className={styles.compareFeatureRow}
                  data-compare-row="others"
                  style={{ '--ri': i } as CSSProperties}>
                  <span className={row.others ? styles.checkYesDim : styles.checkNo}>
                    {row.others ? '✓' : '✗'}
                  </span>
                  <span className={`${styles.compareFeatureLabel} ${!row.others ? styles.compareFeatureLabelDim : ''}`}>
                    {row.feature}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className={styles.compareCallout} data-reveal="up">
            <span className={styles.compareCalloutAccent}>4 features</span>{' '}
            no other tool offers — semantic detection, LaTeX parsing, AI vision extraction, and overlapping chunk analysis.
          </div>
        </div>
      </section>
      <Footer />
    </div>
  )
}
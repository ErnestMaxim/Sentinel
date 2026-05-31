import styles from '../Analyzer.module.css'

export default function ScoreRing({ pct }: { pct: number }) {
  const r      = 52
  const circ   = 2 * Math.PI * r
  const safePct = isNaN(pct) || pct == null ? 0 : pct
  const orig   = 100 - safePct
  const dash   = (orig / 100) * circ
  const col    = orig >= 75 ? '#16a34a' : orig >= 50 ? '#d97706' : '#dc2626'

  return (
    <div className={styles.ring}>
      <svg width="128" height="128" viewBox="0 0 128 128">
        <circle cx="64" cy="64" r={r} fill="none" stroke="#e5e7eb" strokeWidth="7"/>
        <circle cx="64" cy="64" r={r} fill="none" stroke={col} strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circ}`}
          strokeDashoffset={circ / 4}
          style={{ transition: 'stroke-dasharray 1s ease' }}
        />
      </svg>
      <div className={styles.ringCenter}>
        <span className={styles.ringNum} style={{ color: col }}>
          {isNaN(orig) ? '100' : orig.toFixed(0)}%
        </span>
        <span className={styles.ringLabel}>original</span>
      </div>
    </div>
  )
}

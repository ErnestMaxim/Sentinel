import styles from './HistoryPage.module.css'

export function scoreColorClass(score: number): string {
  if (score <= 20) return styles.scoreLow
  if (score <= 50) return styles.scoreMid
  return styles.scoreHigh
}

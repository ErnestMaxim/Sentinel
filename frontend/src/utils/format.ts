// ── Formatting utilities ───────────────────────────────────────────────────────
export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
  })
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

/** Returns a CSS-score-band label: 'low' | 'mid' | 'high' */
export function scoreBand(score: number): 'low' | 'mid' | 'high' {
  if (score <= 20) return 'low'
  if (score <= 50) return 'mid'
  return 'high'
}

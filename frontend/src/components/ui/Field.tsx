import type { ReactNode } from 'react'
import styles from './Field.module.css'

interface Props {
  label:    string
  children: ReactNode
}

export default function Field({ label, children }: Props) {
  // Wrapping <label> implicitly associates it with any form control inside,
  // without needing a matching id/htmlFor pair.
  return (
    <div className={styles.field}>
      <label className={styles.label}>
        <span className={styles.labelText}>{label}</span>
        {children}
      </label>
    </div>
  )
}

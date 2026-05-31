import type { ReactNode } from 'react'
import styles from './Section.module.css'

interface Props {
  title:    string
  desc:     string
  children: ReactNode
}

export default function Section({ title, desc, children }: Props) {
  return (
    <div className={styles.section}>
      <div className={styles.meta}>
        <h2 className={styles.title}>{title}</h2>
        <p  className={styles.desc}>{desc}</p>
      </div>
      <div className={styles.content}>{children}</div>
    </div>
  )
}

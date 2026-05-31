import styles from '../HistoryPage.module.css'

const WIDTHS = ['49%', '58%', '67%', '76%', '85%']

export default function SkeletonRows() {
  return (
    <>
      {WIDTHS.map((w, i) => (
        <div key={i} className={styles.skeletonRow}>
          <div className={styles.skeletonLine} style={{ width: w }} />
          <div className={styles.skeletonLine} style={{ width: '48px', marginLeft: 'auto' }} />
          <div className={styles.skeletonLine} style={{ width: '56px', marginLeft: 'auto' }} />
          <div className={styles.skeletonLine} style={{ width: '72px', marginLeft: 'auto' }} />
          <div className={styles.skeletonLine} style={{ width: '60px', marginLeft: 'auto' }} />
        </div>
      ))}
    </>
  )
}

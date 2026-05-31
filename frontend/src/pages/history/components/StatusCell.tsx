import type { DocumentStatus } from '../../../types/documents'
import styles from '../HistoryPage.module.css'

const STATUS_CONFIG: Record<DocumentStatus, { cls: string; label: string }> = {
  COMPLETED:  { cls: styles.statusDone,    label: 'Done'    },
  FAILED:     { cls: styles.statusFailed,  label: 'Failed'  },
  PROCESSING: { cls: styles.statusRunning, label: 'Running' },
  PENDING:    { cls: styles.statusPending, label: 'Pending' },
}

export default function StatusCell({ status }: { status: DocumentStatus }) {
  const { cls, label } = STATUS_CONFIG[status]
  return (
    <div className={`${styles.statusCell} ${cls}`}>
      <span className={styles.statusDot} />
      {label}
    </div>
  )
}

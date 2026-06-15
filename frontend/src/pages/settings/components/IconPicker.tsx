import { useRef } from 'react'
import { Upload } from 'lucide-react'
import type { IconState } from '../hooks/useIconState'
import styles from './IconPicker.module.css'

interface Props {
  icon:     IconState
  initials: string
}

export default function IconPicker({ icon, initials }: Props) {
  const fileRef = useRef<HTMLInputElement>(null)

  return (
    <div className={styles.area}>
      {/* Preview */}
      <div className={styles.previewWrap}>
        {icon.currentSrc
          ? <img src={icon.currentSrc} alt={icon.label} className={styles.previewImg} />
          : <div className={styles.previewInitials}>{initials}</div>
        }
        <span className={styles.previewLabel}>{icon.label}</span>
      </div>

      {/* Controls */}
      <div className={styles.controls}>
        <div className={styles.nav}>
          <button
            type="button"
            className={styles.navBtn}
            onClick={icon.prev}
            aria-label="Previous icon"
          >
            ←
          </button>
          <div className={styles.dots} aria-hidden="true">
            {Array.from({ length: icon.total }).map((_, i) => (
              <span
                key={i}
                className={`${styles.dot} ${icon.idx === i ? styles.dotActive : ''}`}
              />
            ))}
          </div>
          <button
            type="button"
            className={styles.navBtn}
            onClick={icon.next}
            aria-label="Next icon"
          >
            →
          </button>
        </div>

        {/* Hidden file input — triggered by the button below; not directly reachable */}
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          aria-hidden="true"
          tabIndex={-1}
          style={{ display: 'none' }}
          onChange={e => { const f = e.target.files?.[0]; if (f) icon.upload(f) }}
        />
        <button
          type="button"
          className={styles.uploadBtn}
          onClick={() => fileRef.current?.click()}
        >
          <Upload size={13} aria-hidden="true" />
          Upload photo
        </button>

        {icon.customSrc && (
          <button type="button" className={styles.removeBtn} onClick={icon.remove}>
            Remove custom photo
          </button>
        )}
      </div>
    </div>
  )
}
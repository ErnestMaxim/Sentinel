import type { AuthUser } from '../../../context/AuthContext'
import Field from '../../../components/ui/Field'
import styles from './ProfileSection.module.css'
import formStyles from '../SettingsPage.module.css'

interface Props {
  user:        AuthUser | null
  firstName:   string
  lastName:    string
  saving:      boolean
  msg:         { ok: boolean; text: string } | null
  onFirstName: (v: string) => void
  onLastName:  (v: string) => void
  onSubmit:    (e: React.FormEvent) => void
}

export default function ProfileSection({
  user, firstName, lastName, saving, msg,
  onFirstName, onLastName, onSubmit,
}: Props) {
  return (
    <>
      {/* Live preview of current avatar */}
      <div className={styles.preview}>
        <div className={styles.avatar}>
          {user?.avatar
            ? <img src={user.avatar} alt={user.initials} className={styles.avatarImg} />
            : <span>{user?.initials ?? '?'}</span>
          }
        </div>
        <div>
          <p className={styles.name}>{user?.firstName} {user?.lastName}</p>
          <p className={styles.email}>{user?.email}</p>
        </div>
      </div>

      <form onSubmit={onSubmit} className={formStyles.form}>
        <div className={formStyles.fieldRow}>
          <Field label="First name">
            <input
              className={formStyles.input}
              value={firstName}
              onChange={e => onFirstName(e.target.value)}
              required
            />
          </Field>
          <Field label="Last name">
            <input
              className={formStyles.input}
              value={lastName}
              onChange={e => onLastName(e.target.value)}
              required
            />
          </Field>
        </div>
        {msg && <p className={msg.ok ? formStyles.msgOk : formStyles.msgErr}>{msg.text}</p>}
        <button className={formStyles.saveBtn} disabled={saving}>
          {saving ? 'Saving…' : 'Save changes'}
        </button>
      </form>
    </>
  )
}

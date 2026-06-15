import Field from '../../../components/ui/Field'
import formStyles from '../SettingsPage.module.css'

interface Props {
  currentPw:    string
  newPw:        string
  confirmPw:    string
  saving:       boolean
  msg:          { ok: boolean; text: string } | null
  onCurrentPw:  (v: string) => void
  onNewPw:      (v: string) => void
  onConfirmPw:  (v: string) => void
  onSubmit:     (e: React.FormEvent) => void
}

export default function PasswordSection({
  currentPw, newPw, confirmPw, saving, msg,
  onCurrentPw, onNewPw, onConfirmPw, onSubmit,
}: Props) {
  return (
    <form onSubmit={onSubmit} className={formStyles.form}>
      <Field label="Current password">
        <input
          aria-label="Current password"
          className={formStyles.input}
          type="password"
          value={currentPw}
          onChange={e => onCurrentPw(e.target.value)}
          placeholder="Leave blank if using Google"
          autoComplete="current-password"
        />
      </Field>

      <div className={formStyles.fieldRow}>
        <Field label="New password">
          <input
            aria-label="New password"
            className={formStyles.input}
            type="password"
            value={newPw}
            onChange={e => onNewPw(e.target.value)}
            required
            autoComplete="new-password"
          />
        </Field>
        <Field label="Confirm password">
          <input
            aria-label="Confirm password"
            className={formStyles.input}
            type="password"
            value={confirmPw}
            onChange={e => onConfirmPw(e.target.value)}
            required
            autoComplete="new-password"
          />
        </Field>
      </div>

      {msg && <p className={msg.ok ? formStyles.msgOk : formStyles.msgErr}>{msg.text}</p>}
      <button type="submit" className={formStyles.saveBtn} disabled={saving}>
        {saving ? 'Saving…' : 'Update password'}
      </button>
    </form>
  )
}

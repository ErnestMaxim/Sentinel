import { useState } from 'react'
import { useForm } from '@tanstack/react-form'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { resetPassword }   from '../../api/auth'
import styles from './ResetPasswordPage.module.css'

const MIN_PASSWORD_LEN = 8

export default function ResetPasswordPage() {
  const [submitError,   setSubmitError]   = useState<string | null>(null)
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null)
  const navigate      = useNavigate()
  const [searchParams] = useSearchParams()
  const token          = searchParams.get('token') ?? ''

  const form = useForm({
    defaultValues: { password: '', confirmPassword: '' },
    onSubmit: async ({ value }) => {
      setSubmitError(null); setSubmitSuccess(null)
      if (!token) { setSubmitError('Invalid or missing reset token.'); return }
      if (value.password !== value.confirmPassword) { setSubmitError('Passwords do not match.'); return }
      try {
        await resetPassword(token, value.password)
        setSubmitSuccess('Password updated. Redirecting to sign in…')
        setTimeout(() => navigate('/signin'), 1500)
      } catch (err) {
        setSubmitError(err instanceof Error ? err.message : 'Something went wrong')
      }
    },
  })

  return (
      <section className={styles.authShell}>
        <div className={styles.topBar}>
          <Link to="/signin" className={styles.backLink}>← Back to sign in</Link>
        </div>

        <h1 className={styles.title}>Set a new password</h1>
        <p className={styles.subtitle}>Choose a strong password for your account.</p>

        <form className={styles.form} onSubmit={e => { e.preventDefault(); e.stopPropagation(); form.handleSubmit() }}>
          {[
            { name: 'password'        as const, label: 'New password',      autoComplete: 'new-password'    },
            { name: 'confirmPassword' as const, label: 'Confirm password',  autoComplete: 'new-password'    },
          ].map(({ name, label, autoComplete }) => (
            <form.Field key={name} name={name} validators={{ onChange: ({ value }) => {
              if (!value.trim()) return 'Required'
              if (value.length < MIN_PASSWORD_LEN) return `At least ${MIN_PASSWORD_LEN} characters`
            }}}>
              {field => {
                const hasError = field.state.meta.isTouched && field.state.meta.errors.length > 0
                return (
                  <div className={styles.fieldGroup}>
                    <label htmlFor={field.name} className={styles.label}>{label}</label>
                    <input id={field.name} name={field.name} type="password"
                      autoComplete={autoComplete} placeholder="••••••••"
                      value={field.state.value} onBlur={field.handleBlur}
                      onChange={e => field.handleChange(e.target.value)}
                      className={`${styles.input} ${hasError ? styles.inputError : ''}`} />
                    {hasError && <small className={styles.errorText}>{field.state.meta.errors.map(String).join(', ')}</small>}
                  </div>
                )
              }}
            </form.Field>
          ))}

          <form.Subscribe selector={s => [s.canSubmit, s.isSubmitting]}>
            {([canSubmit, isSubmitting]) => (
              <button type="submit" disabled={!canSubmit} className={styles.submitButton}>
                {isSubmitting ? 'Updating...' : 'Update password'}
              </button>
            )}
          </form.Subscribe>

          {submitError   && <small className={styles.errorText}   role="alert">{submitError}</small>}
          {submitSuccess && <small className={styles.successText} role="status">{submitSuccess}</small>}
        </form>
      </section>
  )
}

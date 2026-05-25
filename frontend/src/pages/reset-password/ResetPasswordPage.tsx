import { useState } from 'react'
import { useForm } from '@tanstack/react-form'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import styles from './ResetPasswordPage.module.css'
import backgroundVideo from '../../assets/videos/background.mp4'
import sentinelLogo from '../../assets/images/sentinel_logo.png'

const MIN_PASSWORD_LENGTH = 8

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token') ?? ''

  const [submitError, setSubmitError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const form = useForm({
    defaultValues: { password: '', confirmPassword: '' },
    onSubmit: async ({ value }) => {
      setSubmitError(null)

      if (!token) {
        setSubmitError('Invalid or missing reset token.')
        return
      }

      const apiBase = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

      try {
        const response = await fetch(`${apiBase}/auth/reset-password`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token, new_password: value.password }),
        })

        const body = await response.json().catch(() => ({}))

        if (!response.ok) {
          const msg = typeof (body as { detail?: unknown }).detail === 'string'
            ? (body as { detail: string }).detail
            : 'Password reset failed. The link may have expired.'
          setSubmitError(msg)
          return
        }

        setDone(true)
        setTimeout(() => navigate('/signin'), 2500)
      } catch {
        setSubmitError('Unable to reach server. Please try again.')
      }
    },
  })

  // No token in URL at all
  if (!token) {
    return (
      <main className={styles.page}>
        <video className={styles.bgVideo} autoPlay loop muted playsInline preload="auto">
          <source src={backgroundVideo} type="video/mp4" />
        </video>
        <div className={styles.overlay} aria-hidden="true" />
        <section className={styles.authShell}>
          <div className={styles.errorState}>
            <div className={styles.errorIcon}>
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="15" y1="9" x2="9" y2="15" />
                <line x1="9" y1="9" x2="15" y2="15" />
              </svg>
            </div>
            <h1 className={styles.title}>Invalid link</h1>
            <p className={styles.subtitle}>
              This reset link is missing or malformed.
            </p>
            <Link to="/forgot-password" className={styles.submitButton} style={{ textDecoration: 'none', display: 'block', textAlign: 'center' }}>
              Request a new link
            </Link>
          </div>
        </section>
        <aside className={styles.logoStage}>
          <img src={sentinelLogo} alt="Sentinel" className={styles.logoMark} />
        </aside>
      </main>
    )
  }

  return (
    <main className={styles.page}>
      <video className={styles.bgVideo} autoPlay loop muted playsInline preload="auto">
        <source src={backgroundVideo} type="video/mp4" />
      </video>
      <div className={styles.overlay} aria-hidden="true" />

      <section className={styles.authShell}>
        {done ? (
          <div className={styles.successState}>
            <div className={styles.successIcon}>
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </div>
            <h1 className={styles.title}>Password updated!</h1>
            <p className={styles.subtitle}>
              Your password has been reset. Redirecting you to sign in…
            </p>
          </div>
        ) : (
          <>
            <div className={styles.topBar}>
              <Link to="/signin" className={styles.backLink}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="15 18 9 12 15 6" />
                </svg>
                Back to sign in
              </Link>
            </div>

            <h1 className={styles.title}>Set new password</h1>
            <p className={styles.subtitle}>
              Choose a strong password — at least {MIN_PASSWORD_LENGTH} characters.
            </p>

            <form
              className={styles.form}
              onSubmit={(e) => {
                e.preventDefault()
                e.stopPropagation()
                form.handleSubmit()
              }}
            >
              {/* New password */}
              <form.Field
                name="password"
                validators={{
                  onChange: ({ value }) => {
                    if (!value) return 'Password is required'
                    if (value.length < MIN_PASSWORD_LENGTH)
                      return `Password must be at least ${MIN_PASSWORD_LENGTH} characters`
                    return undefined
                  },
                }}
              >
                {(field) => {
                  const hasError = field.state.meta.isTouched && field.state.meta.errors.length > 0
                  return (
                    <div className={styles.fieldGroup}>
                      <label htmlFor={field.name} className={styles.label}>New password</label>
                      <input
                        id={field.name}
                        name={field.name}
                        type="password"
                        autoComplete="new-password"
                        autoFocus
                        value={field.state.value}
                        onBlur={field.handleBlur}
                        onChange={(e) => field.handleChange(e.target.value)}
                        placeholder="At least 8 characters"
                        className={`${styles.input} ${hasError ? styles.inputError : ''}`.trim()}
                      />
                      {hasError && (
                        <small className={styles.errorText}>
                          {field.state.meta.errors.map(String).join(', ')}
                        </small>
                      )}
                    </div>
                  )
                }}
              </form.Field>

              {/* Confirm password */}
              <form.Field
                name="confirmPassword"
                validators={{
                  onChangeListenTo: ['password'],
                  onChange: ({ value, fieldApi }) => {
                    if (!value) return 'Please confirm your password'
                    if (value !== fieldApi.form.getFieldValue('password'))
                      return 'Passwords do not match'
                    return undefined
                  },
                }}
              >
                {(field) => {
                  const hasError = field.state.meta.isTouched && field.state.meta.errors.length > 0
                  return (
                    <div className={styles.fieldGroup}>
                      <label htmlFor={field.name} className={styles.label}>Confirm password</label>
                      <input
                        id={field.name}
                        name={field.name}
                        type="password"
                        autoComplete="new-password"
                        value={field.state.value}
                        onBlur={field.handleBlur}
                        onChange={(e) => field.handleChange(e.target.value)}
                        placeholder="Repeat your password"
                        className={`${styles.input} ${hasError ? styles.inputError : ''}`.trim()}
                      />
                      {hasError && (
                        <small className={styles.errorText}>
                          {field.state.meta.errors.map(String).join(', ')}
                        </small>
                      )}
                    </div>
                  )
                }}
              </form.Field>

              <form.Subscribe selector={(state) => [state.canSubmit, state.isSubmitting]}>
                {([canSubmit, isSubmitting]) => (
                  <button
                    type="submit"
                    disabled={!canSubmit}
                    className={styles.submitButton}
                  >
                    {isSubmitting ? 'Updating…' : 'Update password'}
                  </button>
                )}
              </form.Subscribe>

              {submitError && (
                <div className={styles.serverError} role="alert">
                  <span>{submitError}</span>
                  <Link to="/forgot-password" className={styles.retryLink}>
                    Request a new link
                  </Link>
                </div>
              )}
            </form>
          </>
        )}
      </section>

      <aside className={styles.logoStage}>
        <img src={sentinelLogo} alt="Sentinel" className={styles.logoMark} />
      </aside>
    </main>
  )
}
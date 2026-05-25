import { useState } from 'react'
import { useForm } from '@tanstack/react-form'
import { Link } from 'react-router-dom'
import styles from './ForgotPasswordPage.module.css'
import backgroundVideo from '../../assets/videos/background.mp4'
import sentinelLogo from '../../assets/images/sentinel_logo.png'

const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function ForgotPasswordPage() {
  const [submitted, setSubmitted] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const form = useForm({
    defaultValues: { email: '' },
    onSubmit: async ({ value }) => {
      setSubmitError(null)
      const apiBase = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

      try {
        const response = await fetch(`${apiBase}/auth/forgot-password`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: value.email.trim().toLowerCase() }),
        })

        if (!response.ok) {
          const body = await response.json().catch(() => ({}))
          const msg = typeof (body as { detail?: unknown }).detail === 'string'
            ? (body as { detail: string }).detail
            : 'Something went wrong. Please try again.'
          setSubmitError(msg)
          return
        }

        setSubmitted(true)
      } catch {
        setSubmitError('Unable to reach server. Please try again.')
      }
    },
  })

  return (
    <main className={styles.page}>
      <video className={styles.bgVideo} autoPlay loop muted playsInline preload="auto">
        <source src={backgroundVideo} type="video/mp4" />
      </video>
      <div className={styles.overlay} aria-hidden="true" />

      <section className={styles.authShell}>
        <div className={styles.topBar}>
          <Link to="/signin" className={styles.backLink}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
            Back to sign in
          </Link>
        </div>

        {submitted ? (
          <div className={styles.successState}>
            <div className={styles.successIcon}>
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 12
                         19.79 19.79 0 0 1 1.61 3.41 2 2 0 0 1 3.6 1h3a2 2 0 0 1 2 1.72
                         12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91
                         a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45
                         12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>
              </svg>
            </div>
            <h1 className={styles.title}>Check your email</h1>
            <p className={styles.subtitle}>
              If that address is registered, we've sent a reset link.
              It expires in <strong>1 hour</strong>.
            </p>
            <p className={styles.mutedNote}>
              Didn't receive it? Check your spam folder or{' '}
              <button
                type="button"
                className={styles.retryLink}
                onClick={() => setSubmitted(false)}
              >
                try again
              </button>
              .
            </p>
          </div>
        ) : (
          <>
            <h1 className={styles.title}>Forgot password?</h1>
            <p className={styles.subtitle}>
              Enter your email and we'll send you a reset link.
            </p>

            <form
              className={styles.form}
              onSubmit={(e) => {
                e.preventDefault()
                e.stopPropagation()
                form.handleSubmit()
              }}
            >
              <form.Field
                name="email"
                validators={{
                  onChange: ({ value }) => {
                    if (!value.trim()) return 'Email is required'
                    if (!emailRegex.test(value)) return 'Enter a valid email address'
                    return undefined
                  },
                }}
              >
                {(field) => {
                  const hasError = field.state.meta.isTouched && field.state.meta.errors.length > 0
                  return (
                    <div className={styles.fieldGroup}>
                      <label htmlFor={field.name} className={styles.label}>Email</label>
                      <input
                        id={field.name}
                        name={field.name}
                        type="email"
                        autoComplete="email"
                        autoFocus
                        value={field.state.value}
                        onBlur={field.handleBlur}
                        onChange={(e) => field.handleChange(e.target.value)}
                        placeholder="Enter your email"
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
                    {isSubmitting ? 'Sending…' : 'Send reset link'}
                  </button>
                )}
              </form.Subscribe>

              {submitError && (
                <small className={styles.errorText} role="alert">
                  {submitError}
                </small>
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
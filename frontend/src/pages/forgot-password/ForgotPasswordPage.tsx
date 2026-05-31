import { useState } from 'react'
import { useForm } from '@tanstack/react-form'
import { Link } from 'react-router-dom'
import { forgotPassword }   from '../../api/auth'
import styles from './ForgotPasswordPage.module.css'

const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function ForgotPasswordPage() {
  const [submitError,   setSubmitError]   = useState<string | null>(null)
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null)

  const form = useForm({
    defaultValues: { email: '' },
    onSubmit: async ({ value }) => {
      setSubmitError(null); setSubmitSuccess(null)
      try {
        await forgotPassword(value.email)
        setSubmitSuccess('If that email is registered, a reset link has been sent.')
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

        <h1 className={styles.title}>Reset your password</h1>
        <p className={styles.subtitle}>Enter your email and we'll send you a reset link.</p>

        <form className={styles.form} onSubmit={e => { e.preventDefault(); e.stopPropagation(); form.handleSubmit() }}>
          <form.Field name="email" validators={{ onChange: ({ value }) => {
            if (!value.trim()) return 'Email is required'
            if (!emailRegex.test(value)) return 'Enter a valid email address'
          }}}>
            {field => {
              const hasError = field.state.meta.isTouched && field.state.meta.errors.length > 0
              return (
                <div className={styles.fieldGroup}>
                  <label htmlFor={field.name} className={styles.label}>Email</label>
                  <input id={field.name} name={field.name} type="email" autoComplete="email"
                    value={field.state.value} onBlur={field.handleBlur}
                    onChange={e => field.handleChange(e.target.value)}
                    placeholder="Enter your email"
                    className={`${styles.input} ${hasError ? styles.inputError : ''}`} />
                  {hasError && <small className={styles.errorText}>{field.state.meta.errors.map(String).join(', ')}</small>}
                </div>
              )
            }}
          </form.Field>

          <form.Subscribe selector={s => [s.canSubmit, s.isSubmitting]}>
            {([canSubmit, isSubmitting]) => (
              <button type="submit" disabled={!canSubmit} className={styles.submitButton}>
                {isSubmitting ? 'Sending...' : 'Send reset link'}
              </button>
            )}
          </form.Subscribe>

          {submitError   && <small className={styles.errorText}   role="alert">{submitError}</small>}
          {submitSuccess && <small className={styles.successText} role="status">{submitSuccess}</small>}
        </form>
      </section>
  )
}

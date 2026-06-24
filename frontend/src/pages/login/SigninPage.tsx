import { useState } from 'react'
import { useForm } from '@tanstack/react-form'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { login, redirectToGoogle } from '../../api/auth'
import styles from './SigninPage.module.css'

const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function SigninPage() {
  const [submitError,   setSubmitError]   = useState<string | null>(null)
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null)
  const navigate    = useNavigate()
  const { refreshUser } = useAuth()

  const form = useForm({
    defaultValues: { email: '', password: '' },
    onSubmit: async ({ value }) => {
      setSubmitError(null); setSubmitSuccess(null)
      try {
        const token = await login(value.email, value.password)
        localStorage.setItem('access_token', token)
        await refreshUser()
        setSubmitSuccess('Signed in successfully.')
        setTimeout(() => navigate('/'), 500)
      } catch (err) {
        setSubmitError(err instanceof Error ? err.message : 'Sign in failed')
      }
    },
  })

  return (
      <>
        <h1 className={styles.title}>Welcome back</h1>
        <p className={styles.subtitle}>Sign in to continue with Sentinel</p>

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

          <form.Field name="password" validators={{ onChange: ({ value }) => {
            if (!value.trim()) return 'Password is required'
            if (value.length < 8) return 'Password must be at least 8 characters'
          }}}>
            {field => {
              const hasError = field.state.meta.isTouched && field.state.meta.errors.length > 0
              return (
                <div className={styles.fieldGroup}>
                  <label htmlFor={field.name} className={styles.label}>Password</label>
                  <input id={field.name} name={field.name} type="password" autoComplete="current-password"
                    value={field.state.value} onBlur={field.handleBlur}
                    onChange={e => field.handleChange(e.target.value)}
                    placeholder="Enter your password"
                    className={`${styles.input} ${hasError ? styles.inputError : ''}`} />
                  {hasError && <small className={styles.errorText}>{field.state.meta.errors.map(String).join(', ')}</small>}
                </div>
              )
            }}
          </form.Field>

          <div style={{ textAlign: 'right', marginTop: '-4px' }}>
            <Link to="/forgot-password" className={styles.forgotLink}>Forgot password?</Link>
          </div>

          <form.Subscribe selector={s => [s.canSubmit, s.isSubmitting]}>
            {([canSubmit, isSubmitting]) => (
              <button type="submit" disabled={!canSubmit} className={styles.submitButton}>
                {isSubmitting ? 'Signing in...' : 'Sign in'}
              </button>
            )}
          </form.Subscribe>

          {submitError   && <small className={styles.errorText}   role="alert">{submitError}</small>}
          {submitSuccess && <small className={styles.successText} role="status">{submitSuccess}</small>}
        </form>

        <p className={styles.divider}>OR SIGN IN WITH</p>
        <div className={styles.socialRow}>
          <button type="button" className={styles.socialButton} onClick={redirectToGoogle}>
            <img src="/google-icon.svg" alt="" />Google
          </button>
        </div>
        <p className={styles.termsText}>By signing in, you agree to our Terms and Service.</p>
      </>
  )
}

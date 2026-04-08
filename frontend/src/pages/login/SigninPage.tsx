import { useState } from 'react'
import { useForm } from '@tanstack/react-form'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import styles from './SigninPage.module.css'
import backgroundVideo from '../../assets/videos/background.mp4'
import sentinelLogo from '../../assets/images/sentinel_logo.png'

type SigninFormValues = {
  email: string
  password: string
}

const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function SigninPage() {
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null)
  const navigate = useNavigate()
  const { refreshUser } = useAuth()

  const form = useForm({
    defaultValues: {
      email: '',
      password: '',
    } as SigninFormValues,
    onSubmit: async ({ value }) => {
      setSubmitError(null)
      setSubmitSuccess(null)

      const apiBase = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

      try {
        const response = await fetch(`${apiBase}/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email: value.email.trim().toLowerCase(),
            password: value.password,
          }),
        })

        const responseBody = await response.json().catch(() => ({}))

        if (!response.ok) {
          const message =
            typeof (responseBody as { detail?: unknown }).detail === 'string'
              ? (responseBody as { detail: string }).detail
              : 'Sign in failed'
          setSubmitError(message)
          return
        }

        const token =
          typeof (responseBody as { access_token?: unknown }).access_token === 'string'
            ? (responseBody as { access_token: string }).access_token
            : null

        if (!token) {
          setSubmitError('Invalid login response: access token missing.')
          return
        }

        localStorage.setItem('access_token', token)

        // Fetch user profile immediately so navbar updates right away
        await refreshUser()

        setSubmitSuccess('Signed in successfully.')
        setTimeout(() => navigate('/'), 500)
      } catch {
        setSubmitError('Unable to reach server. Please try again.')
      }
    },
  })

  const handleGoogleLogin = () => {
    const apiBase = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'
    // Direct the browser to the backend's Google auth initiation route
    window.location.href = `${apiBase}/auth/google`
  }

  return (
    <main className={styles.page}>
      <video className={styles.bgVideo} autoPlay loop muted playsInline preload="auto">
        <source src={backgroundVideo} type="video/mp4" />
      </video>
      <div className={styles.overlay} aria-hidden="true" />

      <section className={styles.authShell}>
        <div className={styles.topBar}>
          <nav className={styles.modeSwitch} aria-label="Auth mode">
            <Link to="/signup" className={styles.modeButton}>
              Sign up
            </Link>
            <button type="button" className={styles.modeButtonActive}>
              Sign in
            </button>
          </nav>
        </div>

        <h1 className={styles.title}>Welcome back</h1>
        <p className={styles.subtitle}>Sign in to continue with Sentinel</p>

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

          <form.Field
            name="password"
            validators={{
              onChange: ({ value }) => {
                if (!value.trim()) return 'Password is required'
                if (value.length < 8) return 'Password must be at least 8 characters'
                return undefined
              },
            }}
          >
            {(field) => {
              const hasError = field.state.meta.isTouched && field.state.meta.errors.length > 0
              return (
                <div className={styles.fieldGroup}>
                  <label htmlFor={field.name} className={styles.label}>Password</label>
                  <input
                    id={field.name}
                    name={field.name}
                    type="password"
                    autoComplete="current-password"
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                    placeholder="Enter your password"
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
              <button type="submit" disabled={!canSubmit} className={styles.submitButton}>
                {isSubmitting ? 'Signing in...' : 'Sign in'}
              </button>
            )}
          </form.Subscribe>

          {submitError && (
            <small className={styles.errorText} role="alert">{submitError}</small>
          )}
          {submitSuccess && (
            <small className={styles.successText} role="status">{submitSuccess}</small>
          )}
        </form>

        <p className={styles.divider}>OR SIGN IN WITH</p>

        <div className={styles.socialRow}>
          <button 
            type="button" 
            className={styles.socialButton} 
            onClick={handleGoogleLogin}
          >
            <img src="/google-icon.svg" alt="" />
            Google
          </button>
        </div>

        <p className={styles.termsText}>By signing in, you agree to our Terms and Service.</p>
      </section>

      <aside className={styles.logoStage}>
        <img src={sentinelLogo} alt="Sentinel" className={styles.logoMark} />
      </aside>
    </main>
  )
}
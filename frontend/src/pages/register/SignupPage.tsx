import { useState } from 'react'
import { useForm } from '@tanstack/react-form'
import { Link, useNavigate } from 'react-router-dom'
import styles from './SignupPage.module.css'
import backgroundVideo from '../../assets/videos/background.mp4'
import sentinelLogo from '../../assets/images/sentinel_logo.png'

type SignupFormValues = {
  firstName: string
  lastName: string
  email: string
  password: string
}

const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const MIN_PASSWORD_LENGTH = 8

export default function SignupPage() {
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null)
  const navigate = useNavigate()

  const form = useForm({
    defaultValues: {
      firstName: '',
      lastName: '',
      email: '',
      password: '',
    } as SignupFormValues,
    onSubmit: async ({ value }) => {
      setSubmitError(null)
      setSubmitSuccess(null)

      const apiBase = import.meta.env.VITE_API_URL
      const payload = {
        first_name: value.firstName.trim(),
        last_name: value.lastName.trim(),
        email: value.email.trim().toLowerCase(),
        password: value.password,
      }

      try {
        const response = await fetch(`${apiBase}/users/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })

        const responseBody = await response.json().catch(() => ({}))

        if (!response.ok) {
          const message =
            typeof (responseBody as { detail?: unknown }).detail === 'string'
              ? (responseBody as { detail: string }).detail
              : 'Signup failed'
          setSubmitError(message)
          return
        }

        setSubmitSuccess('Account created successfully. Redirecting to sign in...')
        form.reset()
        setTimeout(() => navigate('/signin'), 700)
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
          <nav className={styles.modeSwitch} aria-label="Auth mode">
            <button type="button" className={styles.modeButtonActive}>
              Sign up
            </button>
            <Link to="/signin" className={styles.modeButton}>
              Sign in
            </Link>
          </nav>
        </div>

        <h1 className={styles.title}>Create account</h1>
        <p className={styles.subtitle}>Join Sentinel and start protecting your work.</p>

        <form
          className={styles.form}
          onSubmit={(e) => {
            e.preventDefault()
            e.stopPropagation()
            form.handleSubmit()
          }}
        >
          <div className={styles.nameRow}>
            <form.Field
              name="firstName"
              validators={{
                onChange: ({ value }) => (!value.trim() ? 'First name is required' : undefined),
              }}
            >
              {(field) => {
                const hasError = field.state.meta.isTouched && field.state.meta.errors.length > 0
                return (
                  <div className={styles.fieldGroup}>
                    <label htmlFor={field.name} className={styles.label}>
                      First name
                    </label>
                    <input
                      id={field.name}
                      name={field.name}
                      type="text"
                      autoComplete="given-name"
                      value={field.state.value}
                      onBlur={field.handleBlur}
                      onChange={(e) => field.handleChange(e.target.value)}
                      placeholder="Enter your first name"
                      className={`${styles.input} ${hasError ? styles.inputError : ''}`.trim()}
                    />
                    {hasError ? (
                      <small className={styles.errorText}>
                        {field.state.meta.errors.map(String).join(', ')}
                      </small>
                    ) : null}
                  </div>
                )
              }}
            </form.Field>

            <form.Field
              name="lastName"
              validators={{
                onChange: ({ value }) => (!value.trim() ? 'Last name is required' : undefined),
              }}
            >
              {(field) => {
                const hasError = field.state.meta.isTouched && field.state.meta.errors.length > 0
                return (
                  <div className={styles.fieldGroup}>
                    <label htmlFor={field.name} className={styles.label}>
                      Last name
                    </label>
                    <input
                      id={field.name}
                      name={field.name}
                      type="text"
                      autoComplete="family-name"
                      value={field.state.value}
                      onBlur={field.handleBlur}
                      onChange={(e) => field.handleChange(e.target.value)}
                      placeholder="Enter your last name"
                      className={`${styles.input} ${hasError ? styles.inputError : ''}`.trim()}
                    />
                    {hasError ? (
                      <small className={styles.errorText}>
                        {field.state.meta.errors.map(String).join(', ')}
                      </small>
                    ) : null}
                  </div>
                )
              }}
            </form.Field>
          </div>

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
                  <label htmlFor={field.name} className={styles.label}>
                    Email
                  </label>
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
                  {hasError ? (
                    <small className={styles.errorText}>
                      {field.state.meta.errors.map(String).join(', ')}
                    </small>
                  ) : null}
                </div>
              )
            }}
          </form.Field>

          <form.Field
            name="password"
            validators={{
              onChange: ({ value }) => {
                if (!value.trim()) return 'Password is required'
                if (value.length < MIN_PASSWORD_LENGTH) {
                  return `Password must be at least ${MIN_PASSWORD_LENGTH} characters`
                }
                return undefined
              },
            }}
          >
            {(field) => {
              const hasError = field.state.meta.isTouched && field.state.meta.errors.length > 0
              return (
                <div className={styles.fieldGroup}>
                  <label htmlFor={field.name} className={styles.label}>
                    Password
                  </label>
                  <input
                    id={field.name}
                    name={field.name}
                    type="password"
                    autoComplete="new-password"
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                    placeholder="Create a password"
                    className={`${styles.input} ${hasError ? styles.inputError : ''}`.trim()}
                  />
                  {hasError ? (
                    <small className={styles.errorText}>
                      {field.state.meta.errors.map(String).join(', ')}
                    </small>
                  ) : null}
                </div>
              )
            }}
          </form.Field>

          <form.Subscribe selector={(state) => [state.canSubmit, state.isSubmitting]}>
            {([canSubmit, isSubmitting]) => (
              <button type="submit" disabled={!canSubmit} className={styles.submitButton}>
                {isSubmitting ? 'Creating account...' : 'Create account'}
              </button>
            )}
          </form.Subscribe>

          {submitError ? (
            <small className={styles.errorText} role="alert">
              {submitError}
            </small>
          ) : null}

          {submitSuccess ? (
            <small className={styles.successText} role="status">
              {submitSuccess}
            </small>
          ) : null}
        </form>
      </section>

      <aside className={styles.logoStage}>
        <img src={sentinelLogo} alt="Sentinel" className={styles.logoMark} />
      </aside>
    </main>
  )
}
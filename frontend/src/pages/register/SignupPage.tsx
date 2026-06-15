import { useState } from 'react'
import { useForm } from '@tanstack/react-form'
import { useNavigate } from 'react-router-dom'
import { register }     from '../../api/auth'
import styles from './SignupPage.module.css'

const emailRegex      = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const MIN_PASSWORD_LEN = 8

// ── Field must live at module scope — defining a component inside another
// component resets its state every render (React creates a new type each time).
type SignupForm = ReturnType<typeof useForm<{ firstName: string; lastName: string; email: string; password: string }>>

function Field({ form, name, label, type = 'text', autoComplete, placeholder, validate }: {
  form:          SignupForm
  name:          'firstName' | 'lastName' | 'email' | 'password'
  label:         string
  type?:         string
  autoComplete?: string
  placeholder?:  string
  validate:      (v: string) => string | undefined
}) {
  return (
    <form.Field name={name} validators={{ onChange: ({ value }) => validate(value) }}>
      {field => {
        const hasError = field.state.meta.isTouched && field.state.meta.errors.length > 0
        return (
          <div className={styles.fieldGroup}>
            <label htmlFor={field.name} className={styles.label}>{label}</label>
            <input
              id={field.name} name={field.name} type={type}
              autoComplete={autoComplete} placeholder={placeholder}
              value={field.state.value} onBlur={field.handleBlur}
              onChange={e => field.handleChange(e.target.value)}
              className={`${styles.input} ${hasError ? styles.inputError : ''}`}
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
  )
}

export default function SignupPage() {
  const [submitError,   setSubmitError]   = useState<string | null>(null)
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null)
  const navigate = useNavigate()

  const form = useForm({
    defaultValues: { firstName: '', lastName: '', email: '', password: '' },
    onSubmit: async ({ value }) => {
      setSubmitError(null); setSubmitSuccess(null)
      try {
        await register(value)
        setSubmitSuccess('Account created successfully. Redirecting to sign in...')
        setTimeout(() => navigate('/signin'), 1200)
      } catch (err) {
        setSubmitError(err instanceof Error ? err.message : 'Signup failed')
      }
    },
  })

  return (
      <>
        <h1 className={styles.title}>Create your account</h1>
        <p className={styles.subtitle}>Join Sentinel and start checking documents</p>

        <form className={styles.form} onSubmit={e => { e.preventDefault(); e.stopPropagation(); form.handleSubmit() }}>
          <div className={styles.nameRow}>
            <Field form={form} name="firstName" label="First name" autoComplete="given-name"
              placeholder="First name" validate={v => !v.trim() ? 'Required' : undefined} />
            <Field form={form} name="lastName"  label="Last name"  autoComplete="family-name"
              placeholder="Last name"  validate={v => !v.trim() ? 'Required' : undefined} />
          </div>

          <Field form={form} name="email" label="Email" type="email" autoComplete="email"
            placeholder="Enter your email"
            validate={v => {
              if (!v.trim()) return 'Email is required'
              if (!emailRegex.test(v)) return 'Enter a valid email address'
            }} />

          <Field form={form} name="password" label="Password" type="password" autoComplete="new-password"
            placeholder="Create a password"
            validate={v => {
              if (!v.trim()) return 'Password is required'
              if (v.length < MIN_PASSWORD_LEN) return `At least ${MIN_PASSWORD_LEN} characters`
            }} />

          <form.Subscribe selector={s => [s.canSubmit, s.isSubmitting]}>
            {([canSubmit, isSubmitting]) => (
              <button type="submit" disabled={!canSubmit} className={styles.submitButton}>
                {isSubmitting ? 'Creating account...' : 'Create account'}
              </button>
            )}
          </form.Subscribe>

          {submitError   && <small className={styles.errorText}   role="alert">{submitError}</small>}
          {submitSuccess && <small className={styles.successText} role="status">{submitSuccess}</small>}
        </form>
      </>
  )
}

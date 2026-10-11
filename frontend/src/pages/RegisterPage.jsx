import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client.js'
import { AuthLayout } from '../components/AuthLayout.jsx'
import { useAuth } from '../auth/AuthContext.jsx'

export function RegisterPage() {
  const { token } = useAuth()
  const navigate = useNavigate()
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')

  if (token) {
    return <Navigate to="/app" replace />
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')

    if (password !== confirmPassword) {
      setError('The passwords do not match.')
      return
    }

    setIsLoading(true)
    try {
      await api.register({
        full_name: fullName.trim(),
        email: email.trim(),
        password,
      })
      navigate('/login', {
        replace: true,
        state: { message: 'Your account is ready. Sign in to continue.' },
      })
    } catch (submitError) {
      setError(
        submitError instanceof ApiError
          ? submitError.message
          : 'Account creation could not be completed. Please try again.',
      )
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <AuthLayout
      eyebrow="A good place to begin"
      title="Make space for what matters."
      description="Create your account to start your personal knowledge workspace."
    >
      <form className="auth-form" onSubmit={handleSubmit}>
        <label className="form-field" htmlFor="register-name">
          <span>Full name</span>
          <input
            autoComplete="name"
            id="register-name"
            maxLength={120}
            onChange={(event) => setFullName(event.target.value)}
            required
            type="text"
            value={fullName}
          />
        </label>
        <label className="form-field" htmlFor="register-email">
          <span>Email address</span>
          <input
            autoComplete="email"
            id="register-email"
            onChange={(event) => setEmail(event.target.value)}
            required
            type="email"
            value={email}
          />
        </label>
        <label className="form-field" htmlFor="register-password">
          <span>Password</span>
          <input
            autoComplete="new-password"
            id="register-password"
            maxLength={128}
            minLength={8}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
          <small>Use at least 8 characters.</small>
        </label>
        <label className="form-field" htmlFor="register-confirm-password">
          <span>Confirm password</span>
          <input
            autoComplete="new-password"
            id="register-confirm-password"
            maxLength={128}
            minLength={8}
            onChange={(event) => setConfirmPassword(event.target.value)}
            required
            type="password"
            value={confirmPassword}
          />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button className="auth-submit" disabled={isLoading} type="submit">
          {isLoading ? 'Creating account…' : 'Create account'}
        </button>
      </form>
      <p className="auth-switch">
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </AuthLayout>
  )
}

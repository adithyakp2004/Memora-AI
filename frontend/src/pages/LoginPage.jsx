import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client.js'
import { AuthLayout } from '../components/AuthLayout.jsx'
import { useAuth } from '../auth/AuthContext.jsx'

export function LoginPage() {
  const { login, isLoading, token } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  if (token) {
    return <Navigate to="/app" replace />
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    try {
      await login({ email: email.trim(), password })
      navigate(location.state?.from?.pathname || '/app', { replace: true })
    } catch (submitError) {
      setError(
        submitError instanceof ApiError
          ? submitError.message
          : 'Sign in could not be completed. Please try again.',
      )
    }
  }

  return (
    <AuthLayout
      eyebrow="Welcome back"
      title="A calmer place to pick up."
      description="Sign in to continue to your personal knowledge workspace."
    >
      <form className="auth-form" onSubmit={handleSubmit}>
        {location.state?.message && (
          <p className="form-notice" role="status">
            {location.state.message}
          </p>
        )}
        <label className="form-field" htmlFor="login-email">
          <span>Email address</span>
          <input
            autoComplete="email"
            id="login-email"
            onChange={(event) => setEmail(event.target.value)}
            required
            type="email"
            value={email}
          />
        </label>
        <label className="form-field" htmlFor="login-password">
          <span>Password</span>
          <input
            autoComplete="current-password"
            id="login-password"
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button className="auth-submit" disabled={isLoading} type="submit">
          {isLoading ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
      <p className="auth-switch">
        New to MEMORA? <Link to="/register">Create an account</Link>
      </p>
    </AuthLayout>
  )
}

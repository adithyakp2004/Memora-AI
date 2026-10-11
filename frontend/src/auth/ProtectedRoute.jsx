import { useCallback, useEffect, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext.jsx'

export function ProtectedRoute({ children }) {
  const { token, user, verifySession } = useAuth()
  const location = useLocation()
  const [isVerifying, setIsVerifying] = useState(false)
  const [verificationFailed, setVerificationFailed] = useState(false)

  const runVerification = useCallback(async () => {
    setIsVerifying(true)
    setVerificationFailed(false)
    try {
      await verifySession()
    } catch {
      setVerificationFailed(true)
    } finally {
      setIsVerifying(false)
    }
  }, [verifySession])

  useEffect(() => {
    if (token) {
      runVerification()
    }
  }, [runVerification, token])

  if (!token || !user) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  if (isVerifying) {
    return (
      <main className="auth-shell">
        <p className="session-check" role="status">
          Checking your sign-in…
        </p>
      </main>
    )
  }

  if (verificationFailed) {
    return (
      <main className="auth-shell">
        <section className="auth-card">
          <p className="form-error" role="alert">
            Your session could not be verified. Check your connection and try
            again.
          </p>
          <button
            className="auth-submit session-retry"
            onClick={runVerification}
            type="button"
          >
            Try again
          </button>
        </section>
      </main>
    )
  }

  return children
}

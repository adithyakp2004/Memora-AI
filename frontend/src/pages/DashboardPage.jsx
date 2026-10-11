import { useAuth } from '../auth/AuthContext.jsx'
import { Link } from 'react-router-dom'

export function DashboardPage() {
  const { logout, user } = useAuth()

  return (
    <main className="workspace">
      <header className="topbar">
        <Link className="brand" to="/app" aria-label="MEMORA home">
          <span className="brand-mark" aria-hidden="true">
            m
          </span>
          <span>memora</span>
        </Link>
        <div className="dashboard-user">
          <span className="dashboard-email">{user.email}</span>
          <Link className="text-button" to="/documents">
            Documents
          </Link>
          <Link className="text-button" to="/search">
            Search
          </Link>
          <button className="text-button" onClick={logout} type="button">
            Sign out
          </button>
        </div>
      </header>

      <section className="welcome-card dashboard-welcome">
        <div className="welcome-copy">
          <p className="eyebrow">Your workspace</p>
          <h1 id="dashboard-heading">Good to have you here, {user.full_name}.</h1>
          <p className="intro">
            Your personal knowledge workspace is ready. More ways to collect
            and connect your ideas will take shape here.
          </p>
        </div>
        <div className="orbit-art" aria-hidden="true">
          <span className="orbit orbit-outer" />
          <span className="orbit orbit-inner" />
          <span className="orbit-center">m</span>
          <span className="orbit-spark orbit-spark-one" />
          <span className="orbit-spark orbit-spark-two" />
        </div>
      </section>

      <section className="connection-card dashboard-placeholder">
        <div>
          <p className="eyebrow">A thoughtful beginning</p>
          <h2>Your space is ready for what comes next.</h2>
          <p className="connection-message">
            Upload private documents or search their locally indexed text.
            Answer generation and productivity actions remain future work.
          </p>
        </div>
        <div className="connection-actions">
          <Link className="retry-button" to="/documents">
            Open documents
          </Link>
          <Link className="retry-button" to="/search">
            Search library
          </Link>
        </div>
      </section>

      <footer className="footer">
        <span>Built with care, one step at a time.</span>
        <span>MEMORA · Personal knowledge workspace</span>
      </footer>
    </main>
  )
}

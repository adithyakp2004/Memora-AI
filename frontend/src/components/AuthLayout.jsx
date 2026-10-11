import { Link } from 'react-router-dom'

export function AuthLayout({ children, eyebrow, title, description }) {
  return (
    <main className="auth-shell">
      <header className="topbar auth-topbar">
        <Link className="brand" to="/login" aria-label="MEMORA sign in">
          <span className="brand-mark" aria-hidden="true">
            m
          </span>
          <span>memora</span>
        </Link>
        <span className="topbar-label">PERSONAL KNOWLEDGE WORKSPACE</span>
      </header>

      <section className="auth-card" aria-labelledby="auth-heading">
        <div className="auth-heading">
          <p className="eyebrow">{eyebrow}</p>
          <h1 id="auth-heading">{title}</h1>
          <p className="auth-description">{description}</p>
        </div>
        {children}
      </section>

      <footer className="footer auth-footer">
        <span>Built with care, one step at a time.</span>
        <span>MEMORA · Your knowledge, in one thoughtful place.</span>
      </footer>
    </main>
  )
}

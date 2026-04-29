import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { useAuth } from '../../../context/AuthContext'
import styles from './Navbar.module.css'
import sentinelLogo from '../../../assets/images/sentinel_logo.png'

const SIDEBAR_FULL = 220
const SIDEBAR_MINI = 64

const NAV_ITEMS = [
  { label: 'Check Document', href: '/check',   icon: IconSearch },
  { label: 'My Reports',     href: '/reports',  icon: IconFile },
  { label: 'History',        href: '/history',  icon: IconClock },
  { label: 'Settings',       href: '/settings', icon: IconCog },
]

export default function Navbar() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { user, signOut } = useAuth()
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    document.documentElement.style.setProperty(
      '--sidebar-w',
      `${collapsed ? SIDEBAR_MINI : SIDEBAR_FULL}px`
    )
  }, [collapsed])

  useEffect(() => {
    document.documentElement.style.setProperty('--sidebar-w', `${SIDEBAR_FULL}px`);
    return () => {
      document.documentElement.style.removeProperty('--sidebar-w');
    };
  }, []);

  const handleSignOut = () => {
    signOut()
    setMobileOpen(false)
    navigate('/signin')
  }

  return (
    <>
      {/* ── Mobile top bar ───────────────────── */}
      <header className={styles.mobileBar}>
        <Link to="/" className={styles.mobileLogo}>
          <img src={sentinelLogo} alt="Sentinel" className={styles.mobileLogoImg} />
          <span className={styles.mobileLogoText}>Sentinel</span>
        </Link>
        <button
          type="button"
          className={styles.hamburger}
          onClick={() => setMobileOpen(v => !v)}
          aria-label="Toggle menu"
        >
          <span /><span /><span />
        </button>
      </header>

      {mobileOpen && (
        <div
          className={styles.backdrop}
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* ── Sidebar ──────────────────────────── */}
      <aside
        className={[
          styles.sidebar,
          collapsed ? styles.collapsed : '',
          mobileOpen ? styles.mobileOpen : '',
        ].join(' ')}
      >
        {/* Logo + collapse toggle */}
        <div className={styles.logoRow}>
          {!collapsed && (
            <Link to="/" className={styles.logo} onClick={() => setMobileOpen(false)}>
              <span className={styles.logoText}>Sentinel</span>
            </Link>
          )}
          <button
            type="button"
            className={styles.collapseBtn}
            onClick={() => setCollapsed(v => !v)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? <IconChevronRight /> : <IconChevronLeft />}
          </button>
        </div>

        <div className={styles.sep} />

        {/* Nav links */}
        <nav className={styles.nav}>
          {NAV_ITEMS.map(({ label, href, icon: Icon }) => (
            <Link
              key={label}
              to={href}
              className={[styles.item, pathname === href ? styles.active : ''].join(' ')}
              onClick={() => setMobileOpen(false)}
              title={collapsed ? label : undefined}
            >
              <span className={styles.icon}><Icon /></span>
              {!collapsed && <span className={styles.label}>{label}</span>}
            </Link>
          ))}
        </nav>

        {/* Bottom — auth-aware */}
        <div className={styles.sidebarFooter}>
          <div className={styles.sep} />

          {user ? (
            <>
              <div
                className={styles.userRow}
                title={collapsed ? `${user.firstName} ${user.lastName}` : undefined}
              >
                <span className={styles.avatar}>{user.initials}</span>
                {!collapsed && (
                  <div className={styles.userInfo}>
                    <span className={styles.userName}>
                      {user.firstName} {user.lastName}
                    </span>
                    <span className={styles.userEmail}>{user.email}</span>
                  </div>
                )}
              </div>

              <button
                type="button"
                className={[styles.item, styles.signOutBtn].join(' ')}
                onClick={handleSignOut}
                title={collapsed ? 'Sign out' : undefined}
              >
                <span className={styles.icon}><IconSignOut /></span>
                {!collapsed && <span className={styles.label}>Sign out</span>}
              </button>
            </>
          ) : (
            <>
              <Link
                to="/signin"
                className={styles.item}
                onClick={() => setMobileOpen(false)}
                title={collapsed ? 'Sign in' : undefined}
              >
                <span className={styles.icon}><IconSignIn /></span>
                {!collapsed && <span className={styles.label}>Sign in</span>}
              </Link>

              <Link
                to="/signup"
                className={[styles.cta, collapsed ? styles.ctaCollapsed : ''].join(' ')}
                onClick={() => setMobileOpen(false)}
                title={collapsed ? 'Get started' : undefined}
              >
                {collapsed ? <IconPlus /> : 'Get started'}
              </Link>
            </>
          )}
        </div>
      </aside>
    </>
  )
}

// ── Icons ─────────────────────────────────────────────────────────────────────

function IconSearch() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  )
}

function IconFile() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  )
}

function IconClock() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
    </svg>
  )
}

function IconCog() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  )
}

function IconChevronLeft() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="15 18 9 12 15 6" />
    </svg>
  )
}

function IconChevronRight() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  )
}

function IconSignOut() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  )
}

function IconSignIn() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
      <polyline points="10 17 15 12 10 7" /><line x1="15" y1="12" x2="3" y2="12" />
    </svg>
  )
}

function IconPlus() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  )
}
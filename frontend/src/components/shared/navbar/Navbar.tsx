import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { useAuth } from '../../../context/AuthContext'
import styles from './Navbar.module.css'
import sentinelLogo from '../../../assets/images/sentinel_logo.png'
import {
  ScanSearch,
  History,
  Home,
  ChevronLeft,
  ChevronRight,
  LogOut,
  LogIn,
  UserPlus,
  Menu,
} from 'lucide-react'

const SIDEBAR_FULL = 220
const SIDEBAR_MINI = 64

const NAV_ITEMS = [
  { label: 'Home',       href: '/home', icon: Home   },
  { label: 'Check Document', href: '/check',    icon: ScanSearch },
  { label: 'History',        href: '/history',  icon: History    },
]

export default function Navbar() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { user, loading, signOut } = useAuth()
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem('sidebar-collapsed') === 'true'
  )
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    document.documentElement.style.setProperty(
      '--sidebar-w',
      `${collapsed ? SIDEBAR_MINI : SIDEBAR_FULL}px`
    )
    localStorage.setItem('sidebar-collapsed', String(collapsed))
  }, [collapsed])

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
          <Menu size={20} />
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
            {collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
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
              <span className={styles.icon}><Icon size={16} /></span>
              {!collapsed && <span className={styles.label}>{label}</span>}
            </Link>
          ))}
        </nav>

        {/* Bottom — auth-aware */}
        <div className={styles.sidebarFooter}>
          <div className={styles.sep} />

          {loading ? (
            <div className={styles.authSkeleton} aria-hidden="true">
              <span className={styles.skeletonAvatar} />
              {!collapsed && <span className={styles.skeletonLine} />}
            </div>
          ) : user ? (
            <>
              <Link
                to="/settings"
                className={styles.userRow}
                onClick={() => setMobileOpen(false)}
                title={collapsed ? `${user.firstName} ${user.lastName}` : undefined}
              >
                <span className={styles.avatar}>
                  {user.avatar
                    ? <img src={user.avatar} alt={user.initials} />
                    : user.initials}
                </span>
                {!collapsed && (
                  <div className={styles.userInfo}>
                    <span className={styles.userName}>
                      {user.firstName} {user.lastName}
                    </span>
                    <span className={styles.userEmail}>{user.email}</span>
                  </div>
                )}
              </Link>

              <button
                type="button"
                className={[styles.item, styles.signOutBtn].join(' ')}
                onClick={handleSignOut}
                title={collapsed ? 'Sign out' : undefined}
              >
                <span className={styles.icon}><LogOut size={16} /></span>
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
                <span className={styles.icon}><LogIn size={16} /></span>
                {!collapsed && <span className={styles.label}>Sign in</span>}
              </Link>

              <Link
                to="/signup"
                className={[styles.cta, collapsed ? styles.ctaCollapsed : ''].join(' ')}
                onClick={() => setMobileOpen(false)}
                title={collapsed ? 'Get started' : undefined}
              >
                {collapsed ? <UserPlus size={16} /> : 'Get started'}
              </Link>
            </>
          )}
        </div>
      </aside>
    </>
  )
}
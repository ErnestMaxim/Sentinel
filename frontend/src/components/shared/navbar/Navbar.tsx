import { useLocation, useNavigate } from 'react-router-dom'
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
  Menu,
} from 'lucide-react'
import { useAnalysis } from '../../../context/AnalysisContext'

const SIDEBAR_FULL = 220
const SIDEBAR_MINI = 64

const NAV_ITEMS = [
  { label: 'Home',            href: '/',        icon: Home       },
  { label: 'Check Document',  href: '/check',   icon: ScanSearch },
  { label: 'History',         href: '/history', icon: History    },
]

// All routes in navigation order for direction detection
const ROUTE_ORDER: Record<string, number> = {
  '/': 0,
  '/check': 1,
  '/history': 2,
  '/settings': 3,
  '/report': 4,
  '/signin': 5,
  '/signup': 6,
  '/forgot-password': 7,
  '/reset-password': 8,
}

function setNavDirection(from: string, to: string) {
  const a = ROUTE_ORDER[from] ?? 0
  const b = ROUTE_ORDER[to]   ?? 0
  document.documentElement.dataset.navDir = b >= a ? 'fwd' : 'bwd'
}

function startPageTransition(callback: () => void) {
  if ('startViewTransition' in document) {
    ;(document as Document & { startViewTransition: (cb: () => void) => void })
      .startViewTransition(callback)
  } else {
    callback()
  }
}

export default function Navbar() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { user, loading, signOut } = useAuth()
  const { isRunning } = useAnalysis()
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
    setNavDirection(pathname, '/signin')
    startPageTransition(() => navigate('/signin'))
  }

  function handleNavTo(to: string) {
    setMobileOpen(false)
    setNavDirection(pathname, to)
    startPageTransition(() => navigate(to))
  }

  const activeNavIndex = NAV_ITEMS.findIndex(({ href }) => pathname === href)

  const pillY = activeNavIndex >= 0 ? activeNavIndex * 46 : -200

  return (
    <>
      {/* ── Mobile top bar ───────────────────── */}
      <header className={styles.mobileBar}>
        <button type="button" className={styles.mobileLogo} onClick={() => handleNavTo('/')}>
          <img src={sentinelLogo} alt="Sentinel" className={styles.mobileLogoImg} />
          <span className={styles.mobileLogoText}>Sentinel</span>
        </button>
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
            <button type="button" className={styles.logo} onClick={() => handleNavTo('/')}>
              <span className={styles.logoText}>Sentinel</span>
            </button>
          )}
          <button
            type="button"
            className={styles.collapseBtn}
            onClick={() => setCollapsed(v => !v)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? <ChevronRight size={13} /> : <ChevronLeft size={13} />}
          </button>
        </div>

        <div className={styles.sep} />

        {/* Nav links */}
        <nav className={styles.nav}>
          {/* Sliding active-state pill */}
          {activeNavIndex >= 0 && (
            <div
              className={[
                styles.activePill,
                collapsed ? styles.activePillCollapsed : '',
              ].join(' ')}
              style={{ transform: `translateY(${pillY}px)` }}
              aria-hidden="true"
            />
          )}

          {NAV_ITEMS.map(({ label, href, icon: Icon }) => (
            <button
              key={label}
              type="button"
              className={[styles.item, pathname === href ? styles.active : ''].join(' ')}
              onClick={() => handleNavTo(href)}
              title={collapsed ? label : undefined}
            >
              <span className={styles.icon}><Icon size={16} /></span>
              {!collapsed && <span className={styles.label}>{label}</span>}
              {label === 'Check Document' && isRunning && (
                <span className={styles.analysisPulse} aria-label="Analysis in progress" />
              )}
            </button>
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
              <button
                type="button"
                className={styles.userRow}
                onClick={() => handleNavTo('/settings')}
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
              </button>

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
              <button
                type="button"
                className={styles.item}
                onClick={() => handleNavTo('/signin')}
                title={collapsed ? 'Sign in' : undefined}
              >
                <span className={styles.icon}><LogIn size={16} /></span>
                {!collapsed && <span className={styles.label}>Sign in</span>}
              </button>
            </>
          )}
        </div>
      </aside>
    </>
  )
}
import { useEffect, useState, type ReactNode } from 'react'
import { AuthContext, type AuthUser } from './AuthContext'
import { fetchMe }     from '../api/auth'
import { mapUserDto }  from '../api/mappers/auth.mapper'

// React Compiler is active in this project.
// "use no memo" opts this provider out — the storage event callback and async
// auth flow use patterns the compiler can't safely analyse.
export function AuthProvider({ children }: { children: ReactNode }) {
  "use no memo"

  const [user,    setUser]    = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  async function refreshUser() {
    const token = localStorage.getItem('access_token')
    if (!token) { setUser(null); setLoading(false); return }
    try {
      const dto = await fetchMe(token)
      setUser(mapUserDto(dto))
    } catch {
      setUser(null)
    }
    setLoading(false)
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { refreshUser() }, [])

  // Keep user in sync across browser tabs
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key !== 'access_token') return
      if (e.newValue) refreshUser()
      else setUser(null)
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function signOut() {
    localStorage.removeItem('access_token')
    setUser(null)
  }

  function setUserIcon(url: string | undefined) {
    if (url) localStorage.setItem('sentinel-user-icon', url)
    else     localStorage.removeItem('sentinel-user-icon')
    setUser(prev => prev ? { ...prev, avatar: url } : prev)
  }

  return (
    <AuthContext.Provider value={{ user, loading, signOut, refreshUser, setUserIcon }}>
      {children}
    </AuthContext.Provider>
  )
}
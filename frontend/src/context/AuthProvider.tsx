import { useEffect, useState, type ReactNode } from 'react'
import { AuthContext, type AuthUser } from './AuthContext'
import { fetchMe }     from '../api/auth'
import { mapUserDto }  from '../api/mappers/auth.mapper'

export function AuthProvider({ children }: { children: ReactNode }) {
  "use no memo"

  const [user,    setUser]    = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  async function refreshUser() {
    const token = localStorage.getItem('access_token')
    if (!token) { setUser(null); setLoading(false); return }
    try {
      const dto = await fetchMe(token)
      const storedIcon = localStorage.getItem('sentinel-user-icon') ?? undefined
      setUser({ ...mapUserDto(dto), avatar: storedIcon })
    } catch {
      setUser(null)
    }
    setLoading(false)
  }

  useEffect(() => { refreshUser() }, [])

  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key !== 'access_token') return
      if (e.newValue) refreshUser()
      else setUser(null)
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [])

  function signOut() {
    localStorage.removeItem('access_token')
    setUser(null)
  }

  function setUserIcon(url: string | undefined) {
    try {
      if (url) localStorage.setItem('sentinel-user-icon', url)
      else     localStorage.removeItem('sentinel-user-icon')
    } catch (e) {
      console.warn('localStorage quota exceeded — icon not persisted', e)
    }
    setUser(prev => prev ? { ...prev, avatar: url } : prev)
  }

  return (
    <AuthContext.Provider value={{ user, loading, signOut, refreshUser, setUserIcon }}>
      {children}
    </AuthContext.Provider>
  )
}
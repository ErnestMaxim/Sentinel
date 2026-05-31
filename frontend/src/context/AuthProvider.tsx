import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { AuthContext, type AuthUser } from './AuthContext'
import { fetchMe }     from '../api/auth'
import { mapUserDto }  from '../api/mappers/auth.mapper'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user,    setUser]    = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  const refreshUser = useCallback(async () => {
    const token = localStorage.getItem('access_token')
    if (!token) { setUser(null); setLoading(false); return }
    try {
      const dto     = await fetchMe(token)
      setUser(mapUserDto(dto))
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refreshUser() }, [refreshUser])

  // Keep user in sync across browser tabs
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key !== 'access_token') return
      if (e.newValue) refreshUser()
      else setUser(null)
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [refreshUser])

  const signOut = useCallback(() => {
    localStorage.removeItem('access_token')
    setUser(null)
  }, [])

  const setUserIcon = useCallback((url: string | undefined) => {
    if (url) localStorage.setItem('sentinel-user-icon', url)
    else     localStorage.removeItem('sentinel-user-icon')
    setUser(prev => prev ? { ...prev, avatar: url } : prev)
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, signOut, refreshUser, setUserIcon }}>
      {children}
    </AuthContext.Provider>
  )
}

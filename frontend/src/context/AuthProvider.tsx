import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { AuthContext, type AuthUser } from './AuthContext'

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

function buildInitials(firstName: string, lastName: string, email: string): string {
  const f = firstName.trim().charAt(0).toUpperCase()
  const l = lastName.trim().charAt(0).toUpperCase()
  if (f && l) return `${f}${l}`
  if (f) return f
  return email.charAt(0).toUpperCase() || '?'
}

async function fetchMe(token: string): Promise<AuthUser | null> {
  try {
    const res = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) return null
    const data = await res.json()

    const firstName: string = data.first_name ?? data.firstName ?? ''
    const lastName: string  = data.last_name  ?? data.lastName  ?? ''
    const email: string     = data.email ?? ''

    return {
      email,
      firstName,
      lastName,
      initials: buildInitials(firstName, lastName, email),
    }
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  const refreshUser = useCallback(async () => {
    const token = localStorage.getItem('access_token')
    if (!token) {
      setUser(null)
      setLoading(false)
      return
    }
    const profile = await fetchMe(token)
    setUser(profile)
    setLoading(false)
  }, [])

  useEffect(() => {
    refreshUser()
  }, [refreshUser])

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

  return (
    <AuthContext.Provider value={{ user, loading, signOut, refreshUser }}>
      {children}
    </AuthContext.Provider>
  )
}
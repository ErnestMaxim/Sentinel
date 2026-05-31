import { createContext, useContext } from 'react'

export interface AuthUser {
  email: string
  firstName: string
  lastName: string
  initials: string
  avatar?: string   // optional profile picture URL
}

export interface AuthContextValue {
  user: AuthUser | null
  loading: boolean
  signOut: () => void
  refreshUser: () => Promise<void>
  setUserIcon: (url: string | undefined) => void
}

export const AuthContext = createContext<AuthContextValue>({
  user: null,
  loading: true,
  signOut: () => {},
  refreshUser: async () => {},
  setUserIcon: () => {},
})

// Hook lives here — no component in this file, so Fast Refresh is happy
export function useAuth(): AuthContextValue {
  return useContext(AuthContext)
}
import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { api } from '../api/client.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [session, setSession] = useState({ token: null, user: null })
  const [isLoading, setIsLoading] = useState(false)

  const login = useCallback(async (credentials) => {
    setIsLoading(true)
    try {
      const tokenResult = await api.login(credentials)
      const user = await api.currentUser(tokenResult.access_token)
      setSession({ token: tokenResult.access_token, user })
      return user
    } finally {
      setIsLoading(false)
    }
  }, [])

  const verifySession = useCallback(async () => {
    if (!session.token) {
      return null
    }

    try {
      const user = await api.currentUser(session.token)
      setSession((current) =>
        current.token ? { ...current, user } : current,
      )
      return user
    } catch (error) {
      if (error.status === 401) {
        setSession({ token: null, user: null })
      }
      throw error
    }
  }, [session.token])

  const logout = useCallback(() => {
    setSession({ token: null, user: null })
  }, [])

  const value = useMemo(
    () => ({
      token: session.token,
      user: session.user,
      isLoading,
      login,
      logout,
      verifySession,
    }),
    [isLoading, login, logout, session, verifySession],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider.')
  }
  return context
}

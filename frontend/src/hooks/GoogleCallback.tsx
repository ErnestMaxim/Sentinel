import { useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function GoogleCallback() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { refreshUser } = useAuth()

  useEffect(() => {
    const token = searchParams.get('token')

    if (token) {
      localStorage.setItem('access_token', token)

      refreshUser().then(() => {
    
        navigate('/')
      })
    } else {
      console.error('No token found in callback URL')
      navigate('/signin')
    }
  }, [searchParams, navigate, refreshUser])

  return (
    <div style={{ display: 'flex', justifyContent: 'center', marginTop: '100px' }}>
      <p>Finalizing sign in...</p>
    </div>
  )
}
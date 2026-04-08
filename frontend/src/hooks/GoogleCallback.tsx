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
      // 1. Save the JWT issued by your backend
      localStorage.setItem('access_token', token)
      
      // 2. Refresh the AuthContext to get user details (first_name, email, etc.)
      refreshUser().then(() => {
        // 3. Redirect to dashboard/home
        navigate('/')
      })
    } else {
      // Handle error case
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
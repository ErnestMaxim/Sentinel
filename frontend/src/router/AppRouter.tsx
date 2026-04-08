import { Route, Routes } from 'react-router-dom'
import HomePage from '../pages/home/HomePage'
import SigninPage from '../pages/login/SigninPage'
import SignupPage from '../pages/register/SignupPage'
import GoogleCallback from '../hooks/GoogleCallback'

export default function AppRouter() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/signin" element={<SigninPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/auth/callback" element={<GoogleCallback />} />
      <Route path="*" element={<HomePage />} />
    </Routes>
  )
}
import { Route, Routes } from 'react-router-dom'
import HomePage from '../pages/home/HomePage'
import SigninPage from '../pages/login/SigninPage'
import SignupPage from '../pages/register/SignupPage'
import GoogleCallback from '../hooks/GoogleCallback'
import AnalyzerPage from '../pages/analyzer/AnalyzerPage'
import ForgotPasswordPage from '../pages/forgot-password/ForgotPasswordPage'
import ResetPasswordPage from '../pages/reset-password/ResetPasswordPage'
import HistoryPage from '../pages/history/HistoryPage'

export default function AppRouter() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/signin" element={<SigninPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/auth/callback" element={<GoogleCallback />} />
      <Route path="/check" element={<AnalyzerPage />} />
      <Route path="/history" element={<HistoryPage />}  />
      <Route path="*" element={<HomePage />} />
    </Routes>
  )
}
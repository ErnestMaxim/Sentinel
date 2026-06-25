import { Route, Routes, Outlet, Navigate } from 'react-router-dom'
import HomePage           from '../pages/home/HomePage'
import SigninPage         from '../pages/login/SigninPage'
import SignupPage         from '../pages/register/SignupPage'
import GoogleCallback     from '../hooks/GoogleCallback'
import AnalyzerPage       from '../pages/analyzer/AnalyzerPage'
import ForgotPasswordPage from '../pages/forgot-password/ForgotPasswordPage'
import ResetPasswordPage  from '../pages/reset-password/ResetPasswordPage'
import HistoryPage        from '../pages/history/HistoryPage'
import SettingsPage       from '../pages/settings/SettingsPage'
import AuthShell          from '../components/ui/AuthShell'
import AppLayout          from '../components/ui/AppLayout'
import ReportPage         from '../pages/report/ReportPage'
import { useAuth }        from '../context/AuthContext'

function AuthLayout() {
  return (
    <AuthShell>
      <Outlet />
    </AuthShell>
  )
}

function PrivateRoute() {
  const { user, loading } = useAuth()
  if (loading) return null
  return user ? <Outlet /> : <Navigate to="/signin" replace />
}

export default function AppRouter() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        {/* Public */}
        <Route path="/"    element={<HomePage />} />
        <Route path="*"    element={<HomePage />} />

        {/* Protected */}
        <Route element={<PrivateRoute />}>
          <Route path="/check"    element={<AnalyzerPage />} />
          <Route path="/report"   element={<ReportPage />} />
          <Route path="/history"  element={<HistoryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Route>

      <Route path="/oauth-callback" element={<GoogleCallback />} />

      <Route element={<AuthLayout />}>
        <Route path="/signin"          element={<SigninPage />} />
        <Route path="/signup"          element={<SignupPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password"  element={<ResetPasswordPage />} />
      </Route>
    </Routes>
  )
}
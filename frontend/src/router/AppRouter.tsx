import { Route, Routes, Outlet } from 'react-router-dom'
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
import ReportPage         from '../pages/report/ReportPage'

// Layout route: AuthShell mounts once and stays alive while navigating
// between any auth page — the video never restarts.
function AuthLayout() {
  return (
    <AuthShell>
      <Outlet />
    </AuthShell>
  )
}

export default function AppRouter() {
  return (
    <Routes>
      <Route path="/"              element={<HomePage />} />
      <Route path="/auth/callback" element={<GoogleCallback />} />
      <Route path="/check"         element={<AnalyzerPage />} />
      <Route path="/report"        element={<ReportPage />} />
      <Route path="/history"       element={<HistoryPage />} />
      <Route path="/settings"      element={<SettingsPage />} />

      {/* Auth layout route — shell persists, only Outlet content swaps */}
      <Route element={<AuthLayout />}>
        <Route path="/signin"          element={<SigninPage />} />
        <Route path="/signup"          element={<SignupPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password"  element={<ResetPasswordPage />} />
      </Route>

      <Route path="*" element={<HomePage />} />
    </Routes>
  )
}

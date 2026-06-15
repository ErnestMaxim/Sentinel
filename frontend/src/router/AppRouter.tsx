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
import AppLayout          from '../components/ui/AppLayout'
import ReportPage         from '../pages/report/ReportPage'

// Auth layout: AuthShell mounts once while navigating between auth pages
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
      {/* ── Main app — Navbar lives here, survives all route swaps ── */}
      <Route element={<AppLayout />}>
        <Route path="/"         element={<HomePage />} />
        <Route path="/check"    element={<AnalyzerPage />} />
        <Route path="/report"   element={<ReportPage />} />
        <Route path="/history"  element={<HistoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*"         element={<HomePage />} />
      </Route>

      {/* ── OAuth callback (no chrome needed) ── */}
      <Route path="/oauth-callback" element={<GoogleCallback />} />

      {/* ── Auth pages — AuthShell persists, only Outlet content swaps ── */}
      <Route element={<AuthLayout />}>
        <Route path="/signin"          element={<SigninPage />} />
        <Route path="/signup"          element={<SignupPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password"  element={<ResetPasswordPage />} />
      </Route>
    </Routes>
  )
}

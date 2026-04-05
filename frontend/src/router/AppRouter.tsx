import { Navigate, Route, Routes } from 'react-router-dom'
import SigninPage from '../pages/login/SigninPage'
import SignupPage from '../pages/register/SignupPage'

export default function AppRouter() {

    return (
            <Routes>
            <Route path="/" element={<Navigate to="/signin" replace />} />
            <Route path="/signin" element={<SigninPage />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route path="*" element={<Navigate to="/signin" replace />} />
            </Routes>
        )
}
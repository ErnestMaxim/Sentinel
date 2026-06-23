import './App.css'
import { BrowserRouter } from 'react-router-dom'
import AppRouter from './router/AppRouter'
import { AuthProvider }     from './context/AuthProvider'
import { AnalysisProvider } from './context/AnalysisContext'

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AnalysisProvider>
          <AppRouter />
        </AnalysisProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
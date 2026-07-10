import React, { useState, useEffect, createContext, useContext } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { message } from 'antd'
import AgentConsole from './pages/AgentConsole'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import IntentCenter from './pages/IntentCenter'
import CampaignDetail from './pages/CampaignDetail'
import DataManagement from './pages/DataManagement'
import ConnectorManagement from './pages/ConnectorManagement'
import CreativeManagement from './pages/CreativeManagement'
import MainLayout from './components/MainLayout'
import { authAPI } from './api'

const AuthContext = createContext()

export function useAuth() {
  return useContext(AuthContext)
}

function ProtectedRoute({ children, user }) {
  if (!user) {
    return <Navigate to="/login" replace />
  }
  return children
}

function AppContent() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (token) {
      authAPI.getMe()
        .then(data => {
          setUser(data)
        })
        .catch(() => {
          localStorage.removeItem('token')
          setUser(null)
        })
        .finally(() => {
          setLoading(false)
        })
    } else {
      setLoading(false)
    }
  }, [])

  const handleLogin = async (email, password) => {
    try {
      const result = await authAPI.login(email, password)
      localStorage.setItem('token', result.access_token)
      const userData = await authAPI.getMe()
      setUser(userData)
      message.success('登录成功')
      setTimeout(() => navigate('/dashboard'), 100)
      return true
    } catch (error) {
      message.error('登录失败：' + (error.response?.data?.detail || '未知错误'))
      return false
    }
  }

  const handleLogout = () => {
    localStorage.removeItem('token')
    setUser(null)
    message.success('已退出登录')
    navigate('/login')
  }

  if (loading) {
    return <div style={{ padding: '20px', textAlign: 'center' }}>加载中...</div>
  }

  return (
    <AuthContext.Provider value={{ user, setUser, login: handleLogin, logout: handleLogout }}>
      <Routes>
        <Route path="/login" element={
          user ? <Navigate to="/dashboard" replace /> : <Login onLogin={handleLogin} />
        } />
        <Route path="/dashboard" element={
          <ProtectedRoute user={user}>
            <MainLayout user={user} onLogout={handleLogout}>
              <Dashboard user={user} />
            </MainLayout>
          </ProtectedRoute>
        } />
        <Route path="/intent" element={
          <ProtectedRoute user={user}>
            <MainLayout user={user} onLogout={handleLogout}>
              <IntentCenter user={user} />
            </MainLayout>
          </ProtectedRoute>
        } />
        <Route path="/agent" element={
          <ProtectedRoute user={user}>
            <MainLayout user={user} onLogout={handleLogout}>
              <AgentConsole />
            </MainLayout>
          </ProtectedRoute>
        } />
        <Route path="/campaign/:id" element={
          <ProtectedRoute user={user}>
            <MainLayout user={user} onLogout={handleLogout}>
              <CampaignDetail />
            </MainLayout>
          </ProtectedRoute>
        } />
        <Route path="/data-management" element={
          <ProtectedRoute user={user}>
            <MainLayout user={user} onLogout={handleLogout}>
              <DataManagement />
            </MainLayout>
          </ProtectedRoute>
        } />
        <Route path="/connectors" element={
          <ProtectedRoute user={user}>
            <MainLayout user={user} onLogout={handleLogout}>
              <ConnectorManagement />
            </MainLayout>
          </ProtectedRoute>
        } />
        <Route path="/creatives" element={
          <ProtectedRoute user={user}>
            <MainLayout user={user} onLogout={handleLogout}>
              <CreativeManagement user={user} />
            </MainLayout>
          </ProtectedRoute>
        } />
        <Route path="*" element={
          <Navigate to={user ? "/dashboard" : "/login"} replace />
        } />
      </Routes>
    </AuthContext.Provider>
  )
}

function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  )
}

export default App

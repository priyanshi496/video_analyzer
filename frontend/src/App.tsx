import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useState } from 'react';
import Login from './pages/Login';
import Signup from './pages/Signup';
import Dashboard from './pages/Dashboard';
import Workspace from './pages/Workspace';
import Feed from './pages/Feed';
import Focus from './pages/Focus';
import Analytics from './pages/Analytics';
import { Sidebar } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';
import { BottomNav } from './components/layout/BottomNav';

const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
  const token = localStorage.getItem('token');
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
};

const AppLayout = ({ children }: { children: React.ReactNode }) => {
  const location = useLocation();
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  const getHeaderInfo = () => {
    if (location.pathname === '/') return { title: 'Dashboard', subtitle: 'Manage your video projects' };
    if (location.pathname.startsWith('/project')) return { title: 'Project Workspace', subtitle: 'Upload media and configure generation' };
    if (location.pathname === '/feed') return { title: 'Video Feed', subtitle: 'Watch generated reels' };
    if (location.pathname === '/dashboard') return { title: 'Media Grid', subtitle: 'Manage your assets' };
    if (location.pathname === '/focus') return { title: 'AI Director', subtitle: 'Configure AI rules' };
    if (location.pathname === '/analytics') return { title: 'Performance', subtitle: 'Pipeline analytics' };
    return { title: 'ReelForge AI' };
  };

  const headerInfo = getHeaderInfo();

  return (
    <div className="min-h-screen bg-mesh-gradient flex">
      <Sidebar isOpen={isSidebarOpen} onToggle={() => setIsSidebarOpen(!isSidebarOpen)} />
      <div
        className={`flex-1 flex flex-col transition-all duration-300 ${
          isSidebarOpen ? 'sm:ml-64' : 'sm:ml-20'
        } ml-0 pb-16 lg:pb-0`}
      >
        {/* Header: hidden on mobile for Dashboard and Feed */}
        <div className={`sticky top-0 z-30 ${['/', '/feed'].includes(location.pathname) ? 'hidden sm:block' : ''}`}>
          <Header title={headerInfo.title} subtitle={headerInfo.subtitle} />
        </div>

        <div className="flex-1 flex overflow-hidden">
          {children}
        </div>

        <BottomNav />
      </div>
    </div>
  );
};

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />

        <Route path="/" element={
          <ProtectedRoute>
            <AppLayout>
              <Dashboard />
            </AppLayout>
          </ProtectedRoute>
        } />

        <Route path="/feed" element={
          <ProtectedRoute>
            <AppLayout>
              <Feed />
            </AppLayout>
          </ProtectedRoute>
        } />


        <Route path="/focus" element={
          <ProtectedRoute>
            <AppLayout>
              <Focus />
            </AppLayout>
          </ProtectedRoute>
        } />

        <Route path="/analytics" element={
          <ProtectedRoute>
            <AppLayout>
              <Analytics />
            </AppLayout>
          </ProtectedRoute>
        } />

        <Route path="/project/:id" element={
          <ProtectedRoute>
            <AppLayout>
              <Workspace />
            </AppLayout>
          </ProtectedRoute>
        } />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useState } from 'react';
import Login from './pages/Login';
import { Dashboard } from './components/screens/Dashboard';
import { Workspace } from './components/screens/Workspace';
import { Sidebar } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';

const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
  const token = localStorage.getItem('token');
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
};

const AppLayout = ({ children }: { children: React.ReactNode }) => {
  const location = useLocation();
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  
  const getHeaderInfo = () => {
    if (location.pathname === '/') return { title: 'Dashboard', subtitle: 'Manage your video projects' };
    if (location.pathname.startsWith('/project')) return { title: 'Project Workspace', subtitle: 'Upload media and configure generation' };
    return { title: 'ReelForge AI' };
  };
  
  const headerInfo = getHeaderInfo();

  return (
    <div className="min-h-screen bg-mesh-gradient flex">
      <Sidebar isOpen={isSidebarOpen} onToggle={() => setIsSidebarOpen(!isSidebarOpen)} />
      <div className={`flex-1 flex flex-col transition-all duration-300 ${isSidebarOpen ? 'ml-64' : 'ml-20'}`}>
        <div className="sticky top-0 z-30">
          <Header title={headerInfo.title} subtitle={headerInfo.subtitle} />
        </div>
        <div className="flex-1 flex overflow-hidden">
          {children}
        </div>
      </div>
    </div>
  );
};

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        
        <Route path="/" element={
          <ProtectedRoute>
            <AppLayout>
              <Dashboard />
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

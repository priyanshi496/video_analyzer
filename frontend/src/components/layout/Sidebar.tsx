import { Film, Sparkles, Home, Settings, HelpCircle, Menu } from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';

export function Sidebar({ isOpen, onToggle }: { isOpen: boolean; onToggle: () => void }) {
  const navigate = useNavigate();
  const location = useLocation();
  const currentPath = location.pathname;

  const navItems = [
    { path: '/', label: 'Dashboard', icon: Home },
    { path: '/project', label: 'Projects', icon: Film },
  ];

  const bottomItems = [
    { id: 'settings', label: 'Settings', icon: Settings },
    { id: 'help', label: 'Help', icon: HelpCircle },
  ];

  return (
    <aside className={`fixed left-0 top-0 bottom-0 bg-surface-900 border-r border-surface-800 flex flex-col z-40 transition-all duration-300 ${isOpen ? 'w-64' : 'w-20'}`}>
      {/* Logo & Toggle */}
      <div className={`h-16 flex items-center border-b border-surface-800 ${isOpen ? 'px-6 justify-between' : 'justify-center'}`}>
        <div className="flex items-center gap-3 overflow-hidden">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-primary-500 to-accent-500 flex items-center justify-center flex-shrink-0 shadow-lg shadow-primary-500/20">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          {isOpen && (
            <span className="text-lg font-semibold text-white tracking-tight flex-shrink-0">
              ReelForge<span className="text-primary-400">AI</span>
            </span>
          )}
        </div>
        {isOpen && (
          <button onClick={onToggle} className="p-1.5 rounded-lg text-surface-400 hover:text-white hover:bg-surface-800 transition-colors">
            <Menu className="w-5 h-5" />
          </button>
        )}
      </div>

      {!isOpen && (
        <div className="pt-4 flex justify-center">
          <button onClick={onToggle} className="p-2 rounded-xl text-surface-400 hover:text-white hover:bg-surface-800 transition-colors">
            <Menu className="w-5 h-5" />
          </button>
        </div>
      )}

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4">
        <div className="space-y-2">
          {navItems.map(item => (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              title={!isOpen ? item.label : undefined}
              className={`
                w-full flex items-center ${isOpen ? 'gap-3 px-3 py-2.5' : 'justify-center py-3'} rounded-xl
                transition-all duration-200
                ${currentPath === item.path || (item.path === '/project' && currentPath.startsWith('/project'))
                  ? 'bg-primary-500/10 text-white border border-primary-500/20'
                  : 'text-surface-400 hover:text-white hover:bg-surface-800'}
              `}
            >
              <item.icon className="w-5 h-5 flex-shrink-0" />
              {isOpen && <span className="font-medium">{item.label}</span>}
            </button>
          ))}
        </div>
      </nav>

      {/* Bottom section */}
      <div className="px-3 pb-4 space-y-2">
        {bottomItems.map(item => (
          <button
            key={item.id}
            title={!isOpen ? item.label : undefined}
            className={`w-full flex items-center ${isOpen ? 'gap-3 px-3 py-2.5' : 'justify-center py-3'} rounded-xl text-surface-400 hover:text-white hover:bg-surface-800 transition-all duration-200`}
          >
            <item.icon className="w-5 h-5 flex-shrink-0" />
            {isOpen && <span className="font-medium">{item.label}</span>}
          </button>
        ))}
      </div>
    </aside>
  );
}

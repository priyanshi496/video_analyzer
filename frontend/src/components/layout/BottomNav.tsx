import { Layers, Play, Aperture, BarChart2 } from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';

export function BottomNav() {
  const navigate = useNavigate();
  const location = useLocation();
  const currentPath = location.pathname;

  const items = [
    { path: '/',           label: 'Projects',   icon: Layers },
    { path: '/feed',       label: 'Feed',        icon: Play },
    { path: '/focus',      label: 'Focus',       icon: Aperture },
    { path: '/analytics',  label: 'Analytics',   icon: BarChart2 },
  ];

  return (
    <nav className="lg:hidden fixed bottom-0 left-0 right-0 h-16 bg-white border-t border-slate-100 flex items-center justify-around px-2 z-40 shadow-[0_-4px_16px_rgba(0,0,0,0.04)]">
      {items.map((item) => {
        const isActive =
          item.path === '/'
            ? currentPath === '/'
            : currentPath.startsWith(item.path);

        return (
          <button
            key={item.path}
            onClick={() => navigate(item.path)}
            className={`flex flex-col items-center justify-center py-2 px-3 rounded-2xl transition-all duration-200 ${
              isActive ? 'text-slate-900 scale-110' : 'text-slate-400'
            }`}
          >
            <item.icon
              className={`w-6 h-6 ${isActive ? 'stroke-[2.5]' : 'stroke-[1.8]'}`}
            />
          </button>
        );
      })}
    </nav>
  );
}
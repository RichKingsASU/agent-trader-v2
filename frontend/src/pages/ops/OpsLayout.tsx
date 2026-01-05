import { NavLink, Outlet } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { LayoutDashboard, FileSearch, Newspaper, HeartPulse } from 'lucide-react';

const navItems = [
  { to: '/ops', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/ops/options', label: 'Options Snapshots', icon: FileSearch },
  { to: '/ops/news', label: 'News Events', icon: Newspaper },
  { to: '/ops/jobs', label: 'Job Health', icon: HeartPulse },
];

export default function OpsLayout() {
  return (
    <div className="flex flex-col h-full">
      {/* Top Navigation */}
      <div className="border-b bg-card/50">
        <nav className="flex items-center gap-1 p-2 overflow-x-auto">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors',
                  'hover:bg-accent hover:text-accent-foreground',
                  isActive
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground'
                )
              }
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>

      {/* Page Content */}
      <div className="flex-1 overflow-hidden">
        <Outlet />
      </div>
    </div>
  );
}

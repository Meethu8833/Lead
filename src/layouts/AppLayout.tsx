import { useState } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { useAuthStore, useSidebarStore, useThemeStore, useNotificationStore } from '../app/store';
import { checkPermission } from '../components/auth/PermissionGuard';
import ProfileMenu from '../components/profile/ProfileMenu';
import {
  Menu,
  X,
  Bell,
  Sun,
  Moon,
  ChevronLeft,
  ChevronRight,
  LayoutDashboard,
  Users,
  Download,
  MessageCircle,
  CalendarClock,
  UserCog,
  Settings,
} from 'lucide-react';

interface NavItem {
  name: string;
  path: string;
  icon: React.ComponentType<any>;
  permission: string;
}

// Lead CRM navigation. The ERP modules (Orders, Production, Inventory, Payments,
// Deliveries, Photographers, Attachments) are intentionally absent from the sidebar
// following the pivot to photographer acquisition — their routes still exist and remain
// reachable by direct URL, but they are no longer part of the primary navigation.
const NAV_ITEMS: NavItem[] = [
  { name: 'Dashboard', path: '/', icon: LayoutDashboard, permission: 'dashboard:view' },
  { name: 'Leads', path: '/leads', icon: Users, permission: 'leads:view' },
  { name: 'Import Leads', path: '/leads/import', icon: Download, permission: 'leads:create' },
  { name: 'Campaigns', path: '/campaigns', icon: MessageCircle, permission: 'whatsapp:view' },
  { name: 'Follow-ups', path: '/followups', icon: CalendarClock, permission: 'followups:view' },
  { name: 'Employees', path: '/employees', icon: UserCog, permission: 'employees:view' },
  { name: 'Settings', path: '/settings', icon: Settings, permission: 'settings:view' },
];

/**
 * Whether a nav item should render as the active route.
 *
 * Plain prefix matching is not enough here: `/leads` is a prefix of `/leads/import`, so
 * it would light up both entries at once. An item stays active for its own sub-routes
 * (`/leads/:id` keeps "Leads" highlighted) but yields when a longer nav path is the
 * better match for the current URL.
 */
export const isNavItemActive = (itemPath: string, pathname: string, allPaths: string[]): boolean => {
  if (itemPath === '/') return pathname === '/';
  if (pathname !== itemPath && !pathname.startsWith(`${itemPath}/`)) return false;

  return !allPaths.some(
    (other) =>
      other !== itemPath &&
      other.startsWith(`${itemPath}/`) &&
      (pathname === other || pathname.startsWith(`${other}/`))
  );
};

export default function AppLayout() {
  const location = useLocation();
  const { user, permissions } = useAuthStore();
  const { collapsed, toggle } = useSidebarStore();
  const { theme, setTheme } = useThemeStore();
  const { unreadCount } = useNotificationStore();
  const [mobileOpen, setMobileOpen] = useState(false);

  // Filter navigation items by active employee permissions
  const filteredNavItems = NAV_ITEMS.filter((item) =>
    checkPermission(permissions, item.permission, user?.role?.name)
  );

  // Every declared nav path, so active-state resolution can prefer the most specific
  // match. Taken from NAV_ITEMS rather than the filtered list: which entry wins should
  // not change depending on which ones the current employee may see.
  const navPaths = NAV_ITEMS.map((item) => item.path);

  // Create breadcrumbs based on route paths
  const pathnames = location.pathname.split('/').filter((x) => x);
  const breadcrumbs = [
    { name: 'Home', path: '/' },
    ...pathnames.map((value, index) => {
      const path = `/${pathnames.slice(0, index + 1).join('/')}`;
      const name = value.charAt(0).toUpperCase() + value.slice(1);
      return { name, path };
    }),
  ];

  const toggleTheme = () => {
    setTheme(theme === 'light' ? 'dark' : 'light');
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      {/* ==========================================
          DESKTOP SIDEBAR
          ========================================== */}
      <aside
        className={`hidden md:flex flex-col h-full border-r border-border bg-card transition-all duration-300 ${
          collapsed ? 'w-16' : 'w-64'
        }`}
      >
        {/* Sidebar Header */}
        <div className="flex h-16 items-center justify-between px-4 border-b border-border">
          {!collapsed && (
            <Link to="/" className="flex items-center gap-2">
              <span className="text-lg font-bold tracking-tight text-primary">Colour Labs CRM</span>
            </Link>
          )}
          <button
            onClick={toggle}
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground focus:outline-none"
          >
            {collapsed ? <ChevronRight className="h-5 w-5" /> : <ChevronLeft className="h-5 w-5" />}
          </button>
        </div>

        {/* Sidebar Links */}
        <nav className="flex-1 space-y-1 p-2 overflow-y-auto">
          {filteredNavItems.map((item) => {
            const Icon = item.icon;
            const isActive = isNavItemActive(item.path, location.pathname, navPaths);

            return (
              <Link
                key={item.name}
                to={item.path}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                }`}
              >
                <Icon className="h-5 w-5 flex-shrink-0" />
                {!collapsed && <span>{item.name}</span>}
              </Link>
            );
          })}
        </nav>
      </aside>

      {/* ==========================================
          MOBILE SIDEBAR (DRAWER OVERLAY)
          ========================================== */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden flex">
          {/* Backdrop */}
          <div className="fixed inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />

          {/* Slider Container */}
          <aside className="relative flex w-64 max-w-xs flex-col bg-card border-r border-border h-full p-4 animate-in slide-in-from-left duration-200">
            <div className="flex h-12 items-center justify-between border-b border-border pb-2 mb-4">
              <span className="text-lg font-bold text-primary">Colour Labs CRM</span>
              <button
                onClick={() => setMobileOpen(false)}
                className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground focus:outline-none"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <nav className="flex-1 space-y-1">
              {filteredNavItems.map((item) => {
                const Icon = item.icon;
                const isActive = isNavItemActive(item.path, location.pathname, navPaths);

                return (
                  <Link
                    key={item.name}
                    to={item.path}
                    onClick={() => setMobileOpen(false)}
                    className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                    }`}
                  >
                    <Icon className="h-5 w-5" />
                    <span>{item.name}</span>
                  </Link>
                );
              })}
            </nav>
          </aside>
        </div>
      )}

      {/* ==========================================
          MAIN CONTAINER
          ========================================== */}
      <div className="flex flex-1 flex-col h-full overflow-hidden">
        {/* Top Navbar */}
        <header className="flex h-16 w-full items-center justify-between border-b border-border bg-card px-4 md:px-6">
          {/* Left: Mobile hamburger & breadcrumbs */}
          <div className="flex items-center gap-4">
            <button
              onClick={() => setMobileOpen(true)}
              className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground md:hidden focus:outline-none"
            >
              <Menu className="h-5 w-5" />
            </button>

            {/* Breadcrumbs */}
            <nav className="hidden sm:flex items-center gap-2 text-sm font-medium text-muted-foreground">
              {breadcrumbs.map((crumb, idx) => (
                <div key={crumb.path} className="flex items-center gap-2">
                  {idx > 0 && <span className="text-border">/</span>}
                  {idx === breadcrumbs.length - 1 ? (
                    <span className="text-foreground font-semibold">{crumb.name}</span>
                  ) : (
                    <Link to={crumb.path} className="hover:text-foreground transition-colors">
                      {crumb.name}
                    </Link>
                  )}
                </div>
              ))}
            </nav>
          </div>

          {/* Right: Theme Toggle, Notifications, Profile Dropdown */}
          <div className="flex items-center gap-4">
            {/* Theme switcher */}
            <button
              onClick={toggleTheme}
              className="rounded-full p-2 text-muted-foreground hover:bg-accent hover:text-foreground focus:outline-none"
              title={`Theme: ${theme}`}
            >
              {theme === 'light' && <Sun className="h-5 w-5" />}
              {theme === 'dark' && <Moon className="h-5 w-5" />}
            </button>

            {/* Notifications */}
            <button className="relative rounded-full p-2 text-muted-foreground hover:bg-accent hover:text-foreground focus:outline-none">
              <Bell className="h-5 w-5" />
              {unreadCount > 0 && (
                <span className="absolute right-1 top-1 flex h-4 w-4 items-center justify-center rounded-full bg-red-600 text-[10px] font-bold text-white">
                  {unreadCount}
                </span>
              )}
            </button>

            <span className="h-6 w-px bg-border" />

            {/* Profile Dropdown */}
            <ProfileMenu />
          </div>
        </header>

        {/* Content Outlet */}
        <main className="flex-1 overflow-y-auto bg-background/50 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

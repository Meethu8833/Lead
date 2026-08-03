import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import * as Avatar from '@radix-ui/react-avatar';
import { useAuthStore, useNotificationStore } from '../../app/store';
import { authService } from '../../services/auth';
import { useNavigate, Link } from 'react-router-dom';
import { LogOut, ShieldAlert, Key } from 'lucide-react';

export default function ProfileMenu() {
  const { user, refreshToken, logout: clearAuthStore } = useAuthStore();
  const { addToast } = useNotificationStore();
  const navigate = useNavigate();

  if (!user) return null;

  const initials = `${user.first_name?.[0] || ''}${user.last_name?.[0] || ''}`.toUpperCase();
  const fullName = `${user.first_name} ${user.last_name}`;
  const roleName = user.role?.name || 'Staff';

  const handleLogout = async () => {
    try {
      if (refreshToken) {
        await authService.logout(refreshToken);
      }
    } catch (err) {
      console.error('Failed to log out from server:', err);
    } finally {
      clearAuthStore();
      addToast({
        title: 'Logged Out',
        message: 'You have been successfully logged out.',
        type: 'success',
      });
      navigate('/login');
    }
  };

  const handleLogoutAll = async () => {
    try {
      await authService.logoutAll();
      addToast({
        title: 'All Sessions Closed',
        message: 'Successfully logged out of all devices.',
        type: 'success',
      });
    } catch (err: any) {
      console.error('Failed to logout of all sessions:', err);
      addToast({
        title: 'Error',
        message: err.response?.data?.detail || 'Failed to logout of all sessions.',
        type: 'error',
      });
    } finally {
      clearAuthStore();
      navigate('/login');
    }
  };

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button className="flex items-center gap-2 rounded-full focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2">
          <Avatar.Root className="inline-flex h-9 w-9 select-none items-center justify-center overflow-hidden rounded-full bg-primary/10 border border-border align-middle">
            {user.profile_photo_url ? (
              <Avatar.Image
                className="h-full w-full object-cover"
                src={user.profile_photo_url}
                alt={fullName}
              />
            ) : null}
            <Avatar.Fallback className="flex h-full w-full items-center justify-center bg-primary text-sm font-semibold text-primary-foreground">
              {initials}
            </Avatar.Fallback>
          </Avatar.Root>
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className="z-50 min-w-[220px] rounded-lg border border-border bg-card p-1.5 shadow-lg animate-in fade-in slide-in-from-top-2"
          align="end"
          sideOffset={8}
        >
          {/* Header */}
          <div className="px-2.5 py-2 text-left border-b border-border mb-1.5">
            <p className="text-sm font-semibold text-foreground truncate">{fullName}</p>
            <p className="text-xs text-muted-foreground truncate">{user.email}</p>
            <span className="mt-1.5 inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary uppercase tracking-wider">
              {roleName}
            </span>
          </div>

          {/* Menu Items */}
          <DropdownMenu.Item asChild>
            <Link
              to="/change-password"
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-sm text-foreground hover:bg-accent hover:text-accent-foreground outline-none cursor-pointer"
            >
              <Key className="h-4 w-4 text-muted-foreground" />
              Change Password
            </Link>
          </DropdownMenu.Item>

          <DropdownMenu.Separator className="h-px bg-border my-1.5" />

          <DropdownMenu.Item
            onClick={handleLogout}
            className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/20 outline-none cursor-pointer"
          >
            <LogOut className="h-4 w-4" />
            Sign Out
          </DropdownMenu.Item>

          <DropdownMenu.Item
            onClick={handleLogoutAll}
            className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/20 outline-none cursor-pointer"
          >
            <ShieldAlert className="h-4 w-4" />
            Sign Out All Devices
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { Employee } from '../types';

// ==========================================
// AUTH STORE
// ==========================================

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: Employee | null;
  permissions: string[];
  loading: boolean;
  authenticated: boolean;
  rememberMe: boolean;
  login: (accessToken: string, refreshToken: string, rememberMe: boolean) => void;
  logout: () => void;
  refresh: (accessToken: string, refreshToken: string) => void;
  loadProfile: (user: Employee, permissions: string[]) => void;
  setTokens: (accessToken: string, refreshToken: string) => void;
  clear: () => void;
  setLoading: (loading: boolean) => void;
}

// Helpers to get tokens from storage on startup
const getInitialToken = (key: string): string | null => {
  return localStorage.getItem(key) || sessionStorage.getItem(key);
};

const getInitialRememberMe = (): boolean => {
  return localStorage.getItem('rememberMe') === 'true';
};

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: getInitialToken('accessToken'),
  refreshToken: getInitialToken('refreshToken'),
  user: null,
  permissions: [],
  loading: false,
  authenticated: !!getInitialToken('accessToken'),
  rememberMe: getInitialRememberMe(),

  login: (accessToken, refreshToken, rememberMe) => {
    const storage = rememberMe ? localStorage : sessionStorage;
    storage.setItem('accessToken', accessToken);
    storage.setItem('refreshToken', refreshToken);
    localStorage.setItem('rememberMe', rememberMe ? 'true' : 'false');

    // Clean up alternative storage to avoid collisions
    const otherStorage = rememberMe ? sessionStorage : localStorage;
    otherStorage.removeItem('accessToken');
    otherStorage.removeItem('refreshToken');

    set({
      accessToken,
      refreshToken,
      rememberMe,
      authenticated: true,
    });
  },

  logout: () => {
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken');
    localStorage.removeItem('rememberMe');
    sessionStorage.removeItem('accessToken');
    sessionStorage.removeItem('refreshToken');

    set({
      accessToken: null,
      refreshToken: null,
      user: null,
      permissions: [],
      authenticated: false,
      rememberMe: false,
    });
  },

  refresh: (accessToken, refreshToken) => {
    const isRemember = localStorage.getItem('rememberMe') === 'true';
    const storage = isRemember ? localStorage : sessionStorage;
    storage.setItem('accessToken', accessToken);
    storage.setItem('refreshToken', refreshToken);

    set({
      accessToken,
      refreshToken,
      authenticated: true,
    });
  },

  loadProfile: (user, permissions) => {
    set({
      user,
      permissions,
      authenticated: true,
    });
  },

  setTokens: (accessToken, refreshToken) => {
    const isRemember = localStorage.getItem('rememberMe') === 'true';
    const storage = isRemember ? localStorage : sessionStorage;
    storage.setItem('accessToken', accessToken);
    storage.setItem('refreshToken', refreshToken);

    set({
      accessToken,
      refreshToken,
    });
  },

  clear: () => {
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken');
    localStorage.removeItem('rememberMe');
    sessionStorage.removeItem('accessToken');
    sessionStorage.removeItem('refreshToken');

    set({
      accessToken: null,
      refreshToken: null,
      user: null,
      permissions: [],
      authenticated: false,
      rememberMe: false,
    });
  },

  setLoading: (loading) => set({ loading }),
}));

// ==========================================
// THEME STORE
// ==========================================

export type Theme = 'light' | 'dark' | 'system';

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: 'system',
      setTheme: (theme) => set({ theme }),
    }),
    {
      name: 'colourlabs-theme',
      storage: createJSONStorage(() => localStorage),
    }
  )
);

// ==========================================
// SIDEBAR STORE
// ==========================================

interface SidebarState {
  collapsed: boolean;
  toggle: () => void;
  setCollapsed: (collapsed: boolean) => void;
}

export const useSidebarStore = create<SidebarState>((set) => ({
  collapsed: false,
  toggle: () => set((state) => ({ collapsed: !state.collapsed })),
  setCollapsed: (collapsed) => set({ collapsed }),
}));

// ==========================================
// NOTIFICATION / TOAST STORE
// ==========================================

export interface ToastMessage {
  id: string;
  title?: string;
  message: string;
  type: 'info' | 'success' | 'warning' | 'error';
  duration?: number;
}

interface NotificationState {
  toasts: ToastMessage[];
  unreadCount: number;
  addToast: (toast: Omit<ToastMessage, 'id'>) => void;
  removeToast: (id: string) => void;
  setUnreadCount: (count: number) => void;
  incrementUnread: () => void;
  decrementUnread: () => void;
  clearToasts: () => void;
}

export const useNotificationStore = create<NotificationState>((set) => ({
  toasts: [],
  unreadCount: 0,

  addToast: (toast) => {
    const id = Math.random().toString(36).substring(2, 9);
    const newToast = { ...toast, id };
    
    set((state) => ({
      toasts: [...state.toasts, newToast],
    }));

    // Auto remove toast
    const duration = toast.duration ?? 4000;
    if (duration > 0) {
      setTimeout(() => {
        set((state) => ({
          toasts: state.toasts.filter((t) => t.id !== id),
        }));
      }, duration);
    }
  },

  removeToast: (id) =>
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    })),

  setUnreadCount: (count) => set({ unreadCount: count }),
  incrementUnread: () => set((state) => ({ unreadCount: state.unreadCount + 1 })),
  decrementUnread: () =>
    set((state) => ({ unreadCount: Math.max(0, state.unreadCount - 1) })),
  clearToasts: () => set({ toasts: [] }),
}));

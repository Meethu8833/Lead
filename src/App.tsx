import { useEffect } from 'react';
import { Routes, Route } from 'react-router-dom';
import { useAuthStore } from './app/store';
import { authService } from './services/auth';
import { employeeService } from './services/employee';
import ProtectedRoute from './components/auth/ProtectedRoute';
import AppLayout from './layouts/AppLayout';

// Pages
import Login from './pages/auth/Login';
import ForgotPassword from './pages/auth/ForgotPassword';
import ResetPassword from './pages/auth/ResetPassword';
import ChangePassword from './pages/auth/ChangePassword';
import Dashboard from './pages/dashboard/Dashboard';
import Forbidden from './pages/errors/Forbidden';
import Unauthorized from './pages/errors/Unauthorized';
import NotFound from './pages/errors/NotFound';

export default function App() {
  const { accessToken, authenticated, user, loadProfile, clear, setLoading } = useAuthStore();

  // Restore authenticated session on initial mount/refresh
  useEffect(() => {
    const restoreSession = async () => {
      if (!authenticated || !accessToken || user) {
        return;
      }

      setLoading(true);
      try {
        const [profile, permissions] = await Promise.all([
          authService.me(),
          employeeService.getPermissions(),
        ]);
        loadProfile(profile, permissions);
      } catch (err) {
        console.error('Failed to restore session:', err);
        // Clear auth store if session recovery fails completely (Axios interceptor would have tried refreshing)
        clear();
      } finally {
        setLoading(false);
      }
    };

    restoreSession();
  }, [authenticated, accessToken, user, loadProfile, clear, setLoading]);

  return (
    <Routes>
      {/* Public Authentication Pages */}
      <Route path="/login" element={<Login />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />

      {/* Error Routes */}
      <Route path="/unauthorized" element={<Unauthorized />} />
      <Route path="/forbidden" element={<Forbidden />} />

      {/* Authenticated Dashboard Layout & Protected Pages */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        {/* Dashboard index (requires dashboard:view) */}
        <Route
          index
          element={
            <ProtectedRoute requiredPermission="dashboard:view">
              <Dashboard />
            </ProtectedRoute>
          }
        />

        {/* Change password page (requires active authentication) */}
        <Route
          path="change-password"
          element={
            <ProtectedRoute>
              <ChangePassword />
            </ProtectedRoute>
          }
        />

        {/* Mock/Placeholder routes for future modules protected by respective permissions */}
        <Route
          path="orders"
          element={
            <ProtectedRoute requiredPermission="orders:view">
              <div className="p-6">
                <h1 className="text-3xl font-extrabold tracking-tight">Orders Module</h1>
                <p className="mt-2 text-muted-foreground">Orders list and workflows will go here.</p>
              </div>
            </ProtectedRoute>
          }
        />
        <Route
          path="production"
          element={
            <ProtectedRoute requiredPermission="production:view">
              <div className="p-6">
                <h1 className="text-3xl font-extrabold tracking-tight">Production Module</h1>
                <p className="mt-2 text-muted-foreground">Production queuing and status tracking.</p>
              </div>
            </ProtectedRoute>
          }
        />
        <Route
          path="inventory"
          element={
            <ProtectedRoute requiredPermission="inventory:view">
              <div className="p-6">
                <h1 className="text-3xl font-extrabold tracking-tight">Inventory Module</h1>
                <p className="mt-2 text-muted-foreground">Product catalog, stocks, and adjustments.</p>
              </div>
            </ProtectedRoute>
          }
        />
        <Route
          path="payments"
          element={
            <ProtectedRoute requiredPermission="payments:view">
              <div className="p-6">
                <h1 className="text-3xl font-extrabold tracking-tight">Payments Module</h1>
                <p className="mt-2 text-muted-foreground">Payment transactions and receipt lists.</p>
              </div>
            </ProtectedRoute>
          }
        />
        <Route
          path="deliveries"
          element={
            <ProtectedRoute requiredPermission="deliveries:view">
              <div className="p-6">
                <h1 className="text-3xl font-extrabold tracking-tight">Deliveries Module</h1>
                <p className="mt-2 text-muted-foreground">Courier dispatch and delivery statuses.</p>
              </div>
            </ProtectedRoute>
          }
        />
        <Route
          path="employees"
          element={
            <ProtectedRoute requiredPermission="employees:view">
              <div className="p-6">
                <h1 className="text-3xl font-extrabold tracking-tight">Employees Module</h1>
                <p className="mt-2 text-muted-foreground">Staff profiles and role assignments.</p>
              </div>
            </ProtectedRoute>
          }
        />
        <Route
          path="photographers"
          element={
            <ProtectedRoute requiredPermission="photographers:view">
              <div className="p-6">
                <h1 className="text-3xl font-extrabold tracking-tight">Photographers Module</h1>
                <p className="mt-2 text-muted-foreground">Photographer accounts and client rosters.</p>
              </div>
            </ProtectedRoute>
          }
        />
        <Route
          path="attachments"
          element={
            <ProtectedRoute requiredPermission="attachments:view">
              <div className="p-6">
                <h1 className="text-3xl font-extrabold tracking-tight">Attachments</h1>
                <p className="mt-2 text-muted-foreground">Uploaded assets and document files.</p>
              </div>
            </ProtectedRoute>
          }
        />
        <Route
          path="settings"
          element={
            <ProtectedRoute requiredPermission="settings:view">
              <div className="p-6">
                <h1 className="text-3xl font-extrabold tracking-tight">System Settings</h1>
                <p className="mt-2 text-muted-foreground">Configuration profiles and audit logs.</p>
              </div>
            </ProtectedRoute>
          }
        />
      </Route>

      {/* Global Fallback Route */}
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

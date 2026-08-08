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
import LeadDashboardPage from './features/leads/pages/LeadDashboardPage';
import LeadDetailsPage from './features/leads/pages/LeadDetailsPage';
import LeadPipelinePage from './features/leads/pages/LeadPipelinePage';
import ImportLeadsPage from './features/leads/pages/ImportLeadsPage';
import Forbidden from './pages/errors/Forbidden';
import Unauthorized from './pages/errors/Unauthorized';
import NotFound from './pages/errors/NotFound';
import { OrdersPage } from './features/orders/pages/OrdersPage';
import { OrderDetailsPage } from './features/orders/pages/OrderDetailsPage';
import { CreateOrderPage } from './features/orders/pages/CreateOrderPage';
import { EditOrderPage } from './features/orders/pages/EditOrderPage';

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
        {/* Lead CRM dashboard — the default landing page for the CRM (requires dashboard:view) */}
        <Route
          index
          element={
            <ProtectedRoute requiredPermission="dashboard:view">
              <LeadDashboardPage />
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

        {/* Orders module */}
        <Route
          path="orders"
          element={
            <ProtectedRoute requiredPermission="orders:view">
              <OrdersPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="orders/new"
          element={
            <ProtectedRoute requiredPermission="orders:create">
              <CreateOrderPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="orders/:id"
          element={
            <ProtectedRoute requiredPermission="orders:view">
              <OrderDetailsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="orders/:id/edit"
          element={
            <ProtectedRoute requiredPermission="orders:update">
              <EditOrderPage />
            </ProtectedRoute>
          }
        />

        {/* ==========================================
            LEAD CRM MODULE
            The dashboard links into these routes. Only the dashboard itself is built in
            this phase; the destinations below are placeholders so that every link on it
            resolves instead of falling through to the 404 page.
            ========================================== */}
        {/* The Lead Pipeline (Kanban) board. `leads:view` gates the page; the drag/drop
            and quick actions inside it are separately gated on the permissions their own
            endpoints enforce (leads:update, followups:create, whatsapp:create). */}
        <Route
          path="leads"
          element={
            <ProtectedRoute requiredPermission="leads:view">
              <LeadPipelinePage />
            </ProtectedRoute>
          }
        />
        {/*
          Guarded on `leads:import`, not `leads:create`: bulk-importing hundreds of leads is
          a materially different capability from adding one by hand, and it is the
          permission the backend's import endpoints actually enforce.
        */}
        <Route
          path="leads/import"
          element={
            <ProtectedRoute requiredPermission="leads:import">
              <ImportLeadsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="leads/:id"
          element={
            <ProtectedRoute requiredPermission="leads:view">
              <LeadDetailsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="followups"
          element={
            <ProtectedRoute requiredPermission="followups:view">
              <div className="p-6">
                <h1 className="text-3xl font-extrabold tracking-tight">Follow-ups</h1>
                <p className="mt-2 text-muted-foreground">
                  The full follow-up worklist. Coming in the next phase.
                </p>
              </div>
            </ProtectedRoute>
          }
        />
        <Route
          path="campaigns"
          element={
            <ProtectedRoute requiredPermission="whatsapp:view">
              <div className="p-6">
                <h1 className="text-3xl font-extrabold tracking-tight">WhatsApp Campaigns</h1>
                <p className="mt-2 text-muted-foreground">
                  Campaign list and templates. Coming in the next phase.
                </p>
              </div>
            </ProtectedRoute>
          }
        />
        <Route
          path="campaigns/new"
          element={
            <ProtectedRoute requiredPermission="whatsapp:create">
              <div className="p-6">
                <h1 className="text-3xl font-extrabold tracking-tight">Create Campaign</h1>
                <p className="mt-2 text-muted-foreground">
                  Campaign composer. Coming in the next phase.
                </p>
              </div>
            </ProtectedRoute>
          }
        />
        <Route
          path="campaigns/:id"
          element={
            <ProtectedRoute requiredPermission="whatsapp:view">
              <div className="p-6">
                <h1 className="text-3xl font-extrabold tracking-tight">Campaign Details</h1>
                <p className="mt-2 text-muted-foreground">
                  Campaign recipients and delivery stats. Coming in the next phase.
                </p>
              </div>
            </ProtectedRoute>
          }
        />

        {/* Mock/Placeholder routes for future modules protected by respective permissions */}
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

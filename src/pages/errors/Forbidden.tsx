import { Link } from 'react-router-dom';
import { ShieldAlert } from 'lucide-react';

export default function Forbidden() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-red-100 text-red-600 dark:bg-red-950/30 dark:text-red-400">
        <ShieldAlert className="h-10 w-10" />
      </div>
      <h1 className="mt-6 text-4xl font-extrabold tracking-tight text-foreground">403 - Forbidden</h1>
      <h2 className="mt-2 text-xl font-bold tracking-tight">Access Denied</h2>
      <p className="mt-2 max-w-md text-muted-foreground text-sm">
        You do not have the required permissions to access this page. Please contact your system administrator if you believe this is an error.
      </p>
      <div className="mt-8 flex gap-4">
        <Link
          to="/"
          className="inline-flex items-center rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/95 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2"
        >
          Go Back Home
        </Link>
        <Link
          to="/login"
          className="inline-flex items-center rounded-md border border-input bg-background px-4 py-2.5 text-sm font-semibold text-foreground hover:bg-accent focus:outline-none"
        >
          Switch Account
        </Link>
      </div>
    </div>
  );
}

import { Link } from 'react-router-dom';
import { UserX } from 'lucide-react';

export default function Unauthorized() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-amber-100 text-amber-600 dark:bg-amber-950/30 dark:text-amber-400">
        <UserX className="h-10 w-10" />
      </div>
      <h1 className="mt-6 text-4xl font-extrabold tracking-tight text-foreground">401 - Unauthorized</h1>
      <h2 className="mt-2 text-xl font-bold tracking-tight">Session Expired or Invalid</h2>
      <p className="mt-2 max-w-md text-muted-foreground text-sm">
        Your current session is either invalid or has expired. Please sign in again to access the application.
      </p>
      <div className="mt-8">
        <Link
          to="/login"
          className="inline-flex items-center rounded-md bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/95 focus:outline-none focus:ring-2 focus:ring-primary"
        >
          Sign In Again
        </Link>
      </div>
    </div>
  );
}

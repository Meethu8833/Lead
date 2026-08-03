import { useNotificationStore, ToastMessage } from '../../app/store';
import { X, CheckCircle, AlertTriangle, AlertCircle, Info } from 'lucide-react';

export default function ToastProvider() {
  const { toasts, removeToast } = useNotificationStore();

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex w-full max-w-md flex-col gap-2 p-4 sm:bottom-6 sm:right-6">
      {toasts.map((toast: ToastMessage) => (
        <div
          key={toast.id}
          className={`flex items-start gap-3 rounded-lg border p-4 shadow-lg backdrop-blur-md transition-all duration-300 animate-in fade-in slide-in-from-bottom-4 ${
            toast.type === 'success'
              ? 'border-emerald-500/20 bg-emerald-50 text-emerald-950 dark:bg-emerald-950/20 dark:text-emerald-50'
              : toast.type === 'error'
              ? 'border-red-500/20 bg-red-50 text-red-950 dark:bg-red-950/20 dark:text-red-50'
              : toast.type === 'warning'
              ? 'border-amber-500/20 bg-amber-50 text-amber-950 dark:bg-amber-950/20 dark:text-amber-50'
              : 'border-blue-500/20 bg-blue-50 text-blue-950 dark:bg-blue-950/20 dark:text-blue-50'
          }`}
        >
          <div className="flex-shrink-0 mt-0.5">
            {toast.type === 'success' && <CheckCircle className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />}
            {toast.type === 'error' && <AlertCircle className="h-5 w-5 text-red-600 dark:text-red-400" />}
            {toast.type === 'warning' && <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400" />}
            {toast.type === 'info' && <Info className="h-5 w-5 text-blue-600 dark:text-blue-400" />}
          </div>
          <div className="flex-1 space-y-1">
            {toast.title && <h4 className="text-sm font-semibold">{toast.title}</h4>}
            <p className="text-xs opacity-90">{toast.message}</p>
          </div>
          <button
            onClick={() => removeToast(toast.id)}
            className="flex-shrink-0 text-current hover:opacity-80 focus:outline-none focus:ring-1 focus:ring-current rounded-sm"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  );
}

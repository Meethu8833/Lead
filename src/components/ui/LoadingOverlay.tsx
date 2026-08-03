import { cn } from '../../utils/cn';
import { Spinner } from './Spinner';

export interface LoadingOverlayProps {
  visible: boolean;
  fullscreen?: boolean;
  blur?: boolean;
  message?: string;
  className?: string;
}

export const LoadingOverlay = ({
  visible,
  fullscreen = false,
  blur = true,
  message,
  className,
}: LoadingOverlayProps) => {
  if (!visible) return null;

  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 bg-background/60 dark:bg-zinc-950/60 transition-all duration-200',
        fullscreen ? 'fixed inset-0 z-[9999]' : 'absolute inset-0 z-50',
        blur && 'backdrop-blur-sm',
        className
      )}
      data-testid="loading-overlay"
      aria-busy="true"
      aria-live="polite"
    >
      <div className="flex flex-col items-center justify-center p-6 rounded-lg bg-card/90 dark:bg-zinc-900/90 border border-border shadow-lg max-w-xs text-center">
        <Spinner size="lg" className="text-primary mb-2" data-testid="loading-overlay-spinner" />
        {message && (
          <p className="text-sm font-medium text-foreground animate-pulse mt-1" data-testid="loading-overlay-message">
            {message}
          </p>
        )}
      </div>
    </div>
  );
};

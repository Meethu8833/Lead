import * as React from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from './Dialog';
import { Button } from './Button';
import { cn } from '../../utils/cn';
import { AlertTriangle, CheckCircle2, HelpCircle } from 'lucide-react';

export interface ConfirmationDialogProps {
  isOpen: boolean;
  title: string;
  description: string;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
  variant?: 'danger' | 'warning' | 'success' | 'info';
  confirmText?: string;
  cancelText?: string;
  isLoading?: boolean;
}

export const ConfirmationDialog = ({
  isOpen,
  title,
  description,
  onConfirm,
  onCancel,
  variant = 'info',
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  isLoading = false,
}: ConfirmationDialogProps) => {
  const [localLoading, setLocalLoading] = React.useState(false);
  const activeLoading = isLoading || localLoading;

  const handleConfirm = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      setLocalLoading(true);
      await onConfirm();
    } catch (err) {
      console.error('Confirmation action failed:', err);
    } finally {
      setLocalLoading(false);
    }
  };

  const variantConfigs = {
    danger: {
      icon: <AlertTriangle className="h-6 w-6 text-destructive" />,
      iconBg: 'bg-destructive/10 dark:bg-destructive/20',
      confirmVariant: 'danger' as const,
      borderAccent: 'border-t-4 border-t-destructive',
    },
    warning: {
      icon: <AlertTriangle className="h-6 w-6 text-amber-600 dark:text-amber-500" />,
      iconBg: 'bg-amber-100 dark:bg-amber-950/40',
      confirmVariant: 'primary' as const, // Or secondary/warning. Button does not have warning. variant primary or outline works. Let's use primary.
      borderAccent: 'border-t-4 border-t-amber-500',
    },
    success: {
      icon: <CheckCircle2 className="h-6 w-6 text-emerald-600 dark:text-emerald-500" />,
      iconBg: 'bg-emerald-100 dark:bg-emerald-950/40',
      confirmVariant: 'success' as const,
      borderAccent: 'border-t-4 border-t-emerald-500',
    },
    info: {
      icon: <HelpCircle className="h-6 w-6 text-primary" />,
      iconBg: 'bg-primary/10 dark:bg-primary/20',
      confirmVariant: 'primary' as const,
      borderAccent: 'border-t-4 border-t-primary',
    },
  };

  const currentConfig = variantConfigs[variant];

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && !activeLoading && onCancel()}>
      <DialogContent
        size="sm"
        showCloseButton={!activeLoading}
        className={cn('p-0 overflow-hidden', currentConfig.borderAccent)}
        data-testid="confirmation-dialog"
      >
        <div className="p-6">
          <div className="flex items-start gap-4">
            <div className={cn('p-2.5 rounded-full shrink-0', currentConfig.iconBg)} data-testid="confirmation-icon">
              {currentConfig.icon}
            </div>
            <div className="flex-1 space-y-1">
              <DialogHeader className="text-left">
                <DialogTitle className="text-base font-semibold text-foreground">
                  {title}
                </DialogTitle>
              </DialogHeader>
              <DialogDescription className="text-sm text-muted-foreground whitespace-pre-wrap leading-relaxed mt-1">
                {description}
              </DialogDescription>
            </div>
          </div>
        </div>

        <DialogFooter className="bg-muted/30 dark:bg-zinc-900/30 px-6 py-4 border-t border-border flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2 gap-2 mt-0">
          <Button
            variant="outline"
            onClick={onCancel}
            disabled={activeLoading}
            data-testid="confirmation-cancel"
          >
            {cancelText}
          </Button>
          <Button
            variant={currentConfig.confirmVariant}
            onClick={handleConfirm}
            isLoading={activeLoading}
            data-testid="confirmation-confirm"
          >
            {confirmText}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

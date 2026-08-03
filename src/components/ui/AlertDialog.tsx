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
import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react';

export interface AlertDialogProps {
  isOpen: boolean;
  title: string;
  description: string;
  onAcknowledge: () => void;
  variant?: 'error' | 'warning' | 'success' | 'info';
  acknowledgeText?: string;
  icon?: React.ReactNode;
}

export const AlertDialog = ({
  isOpen,
  title,
  description,
  onAcknowledge,
  variant = 'info',
  acknowledgeText = 'OK',
  icon,
}: AlertDialogProps) => {
  const variantConfigs = {
    error: {
      icon: <XCircle className="h-6 w-6 text-destructive" />,
      iconBg: 'bg-destructive/10 dark:bg-destructive/20',
      btnVariant: 'danger' as const,
      borderAccent: 'border-t-4 border-t-destructive',
    },
    warning: {
      icon: <AlertTriangle className="h-6 w-6 text-amber-600 dark:text-amber-500" />,
      iconBg: 'bg-amber-100 dark:bg-amber-950/40',
      btnVariant: 'primary' as const,
      borderAccent: 'border-t-4 border-t-amber-500',
    },
    success: {
      icon: <CheckCircle2 className="h-6 w-6 text-emerald-600 dark:text-emerald-500" />,
      iconBg: 'bg-emerald-100 dark:bg-emerald-950/40',
      btnVariant: 'success' as const,
      borderAccent: 'border-t-4 border-t-emerald-500',
    },
    info: {
      icon: <Info className="h-6 w-6 text-primary" />,
      iconBg: 'bg-primary/10 dark:bg-primary/20',
      btnVariant: 'primary' as const,
      borderAccent: 'border-t-4 border-t-primary',
    },
  };

  const currentConfig = variantConfigs[variant];
  const displayIcon = icon || currentConfig.icon;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onAcknowledge()}>
      <DialogContent
        size="sm"
        showCloseButton={false}
        className={cn('p-0 overflow-hidden', currentConfig.borderAccent)}
        data-testid="alert-dialog"
      >
        <div className="p-6">
          <div className="flex items-start gap-4">
            {displayIcon && (
              <div className={cn('p-2.5 rounded-full shrink-0', currentConfig.iconBg)} data-testid="alert-icon">
                {displayIcon}
              </div>
            )}
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

        <DialogFooter className="bg-muted/30 dark:bg-zinc-900/30 px-6 py-4 border-t border-border flex justify-end gap-2 mt-0">
          <Button
            variant={currentConfig.btnVariant}
            onClick={onAcknowledge}
            className="px-5"
            data-testid="alert-acknowledge"
          >
            {acknowledgeText}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

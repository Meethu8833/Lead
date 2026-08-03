import * as React from 'react';
import { cn } from '../../utils/cn';
import { Spinner } from './Spinner';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger' | 'success';
  size?: 'sm' | 'md' | 'lg';
  isLoading?: boolean;
  fullWidth?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = 'primary',
      size = 'md',
      isLoading = false,
      disabled,
      fullWidth = false,
      leftIcon,
      rightIcon,
      children,
      type = 'button',
      ...props
    },
    ref
  ) => {
    const baseStyles =
      'inline-flex items-center justify-center font-medium rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 relative select-none';

    const variants = {
      primary: 'bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:ring-ring',
      secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80 focus-visible:ring-ring',
      outline: 'border border-input bg-background text-foreground hover:bg-accent hover:text-accent-foreground focus-visible:ring-ring',
      ghost: 'text-foreground hover:bg-accent hover:text-accent-foreground focus-visible:ring-ring',
      danger: 'bg-destructive text-destructive-foreground hover:bg-destructive/90 focus-visible:ring-ring',
      success: 'bg-emerald-600 text-white hover:bg-emerald-600/90 dark:bg-emerald-700 dark:hover:bg-emerald-700/90 focus-visible:ring-emerald-500',
    };

    const sizes = {
      sm: 'h-8 px-3 text-xs gap-1.5',
      md: 'h-10 px-4 text-sm gap-2',
      lg: 'h-12 px-6 text-base gap-2.5',
    };

    const spinnerSizes = {
      sm: 'sm' as const,
      md: 'sm' as const,
      lg: 'md' as const,
    };

    const isDisabled = disabled || isLoading;

    return (
      <button
        ref={ref}
        type={type}
        disabled={isDisabled}
        className={cn(
          baseStyles,
          variants[variant],
          sizes[size],
          fullWidth && 'w-full',
          className
        )}
        {...props}
      >
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center" data-testid="button-spinner-container">
            <Spinner size={spinnerSizes[size]} />
          </div>
        )}

        <span
          data-testid="button-content"
          className={cn(
            'inline-flex items-center justify-center gap-1.5',
            isLoading && 'invisible opacity-0'
          )}
        >
          {leftIcon && <span className="inline-flex shrink-0" data-testid="button-left-icon">{leftIcon}</span>}
          {children}
          {rightIcon && <span className="inline-flex shrink-0" data-testid="button-right-icon">{rightIcon}</span>}
        </span>
      </button>
    );
  }
);

Button.displayName = 'Button';

import * as React from 'react';
import { Input, InputProps } from './Input';
import { Eye, EyeOff } from 'lucide-react';
import { cn } from '../../utils/cn';

export interface PasswordInputProps extends Omit<InputProps, 'type' | 'suffix'> {}

export const PasswordInput = React.forwardRef<HTMLInputElement, PasswordInputProps>(
  ({ disabled, className, ...props }, ref) => {
    const [showPassword, setShowPassword] = React.useState(false);
    const inputRef = React.useRef<HTMLInputElement>(null);

    // Keep both refs in sync
    React.useImperativeHandle(ref, () => inputRef.current!);

    const togglePasswordVisibility = () => {
      if (disabled) return;

      const input = inputRef.current;
      if (input) {
        // Capture cursor selection boundaries
        const selectionStart = input.selectionStart;
        const selectionEnd = input.selectionEnd;

        setShowPassword((prev) => !prev);

        // Re-apply cursor position in the next paint cycle to avoid jumping
        requestAnimationFrame(() => {
          if (input) {
            input.focus();
            input.setSelectionRange(selectionStart, selectionEnd);
          }
        });
      } else {
        setShowPassword((prev) => !prev);
      }
    };

    const type = showPassword ? 'text' : 'password';

    const suffixButton = (
      <button
        type="button"
        disabled={disabled}
        onClick={togglePasswordVisibility}
        className={cn(
          'text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-sm p-0.5 disabled:opacity-50 disabled:pointer-events-none transition-colors'
        )}
        aria-label={showPassword ? 'Hide password' : 'Show password'}
        data-testid="password-toggle"
      >
        {showPassword ? (
          <EyeOff className="h-4 w-4" data-testid="eye-off-icon" />
        ) : (
          <Eye className="h-4 w-4" data-testid="eye-icon" />
        )}
      </button>
    );

    return (
      <Input
        ref={inputRef}
        type={type}
        disabled={disabled}
        suffix={suffixButton}
        className={className}
        {...props}
      />
    );
  }
);

PasswordInput.displayName = 'PasswordInput';

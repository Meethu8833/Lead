import * as React from 'react';
import { cn } from '../../utils/cn';

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  helperText?: string;
  autoResize?: boolean;
  showMaxLength?: boolean;
  fullWidth?: boolean;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  (
    {
      className,
      label,
      error,
      helperText,
      autoResize = false,
      showMaxLength = false,
      fullWidth = false,
      maxLength,
      value,
      defaultValue,
      onChange,
      required,
      disabled,
      id,
      ...props
    },
    ref
  ) => {
    const generatedId = React.useId();
    const textareaId = id || generatedId;
    const helperId = `${textareaId}-helper`;
    const errorId = `${textareaId}-error`;

    const textareaRef = React.useRef<HTMLTextAreaElement>(null);
    React.useImperativeHandle(ref, () => textareaRef.current!);

    // Handle character count state
    const getInitialLength = () => {
      if (value !== undefined) return String(value).length;
      if (defaultValue !== undefined) return String(defaultValue).length;
      return 0;
    };
    const [charLength, setCharLength] = React.useState(getInitialLength);

    // Sync character length if value updates from parent
    React.useEffect(() => {
      if (value !== undefined) {
        setCharLength(String(value).length);
      }
    }, [value]);

    const adjustHeight = React.useCallback(() => {
      const textarea = textareaRef.current;
      if (autoResize && textarea) {
        textarea.style.height = 'auto';
        textarea.style.height = `${textarea.scrollHeight}px`;
      }
    }, [autoResize]);

    React.useEffect(() => {
      adjustHeight();
      // Also adjust height on window resize to ensure correct bounds
      window.addEventListener('resize', adjustHeight);
      return () => window.removeEventListener('resize', adjustHeight);
    }, [adjustHeight, value, defaultValue]);

    const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setCharLength(e.target.value.length);
      adjustHeight();
      if (onChange) {
        onChange(e);
      }
    };

    return (
      <div className={cn('flex flex-col gap-1.5', fullWidth ? 'w-full' : 'w-auto')}>
        {label && (
          <label
            htmlFor={textareaId}
            className={cn(
              'text-sm font-medium text-foreground select-none',
              disabled && 'opacity-50'
            )}
            data-testid="textarea-label"
          >
            {label}
            {required && <span className="text-destructive ml-1" data-testid="textarea-required-star">*</span>}
          </label>
        )}

        <textarea
          id={textareaId}
          ref={textareaRef}
          disabled={disabled}
          maxLength={maxLength}
          onChange={handleChange}
          value={value}
          defaultValue={defaultValue}
          aria-invalid={error ? 'true' : 'false'}
          aria-describedby={
            error ? errorId : helperText ? helperId : undefined
          }
          className={cn(
            'flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 transition-colors',
            autoResize && 'resize-none overflow-hidden',
            error && 'border-destructive focus-visible:ring-destructive',
            className
          )}
          {...props}
        />

        <div className="flex justify-between items-start gap-2 mt-0.5">
          <div className="flex-1">
            {error ? (
              <p
                id={errorId}
                className="text-xs font-medium text-destructive"
                data-testid="textarea-error"
              >
                {error}
              </p>
            ) : (
              helperText && (
                <p
                  id={helperId}
                  className="text-xs text-muted-foreground"
                  data-testid="textarea-helper"
                >
                  {helperText}
                </p>
              )
            )}
          </div>

          {showMaxLength && maxLength !== undefined && (
            <p
              className="text-xs text-muted-foreground select-none shrink-0"
              data-testid="textarea-counter"
            >
              {charLength} / {maxLength}
            </p>
          )}
        </div>
      </div>
    );
  }
);

Textarea.displayName = 'Textarea';

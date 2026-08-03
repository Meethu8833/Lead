import * as React from 'react';
import { cn } from '../../utils/cn';

export interface RadioOption {
  label: string;
  value: string;
  disabled?: boolean;
}

export interface RadioGroupProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, 'onChange'> {
  name: string;
  options: RadioOption[];
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  orientation?: 'horizontal' | 'vertical';
  error?: string;
  label?: string;
  disabled?: boolean;
}

export const RadioGroup = React.forwardRef<HTMLDivElement, RadioGroupProps>(
  (
    {
      className,
      name,
      options,
      value,
      defaultValue,
      onChange,
      orientation = 'vertical',
      error,
      label,
      disabled = false,
      ...props
    },
    ref
  ) => {
    const [selectedValue, setSelectedValue] = React.useState<string | undefined>(
      value !== undefined ? value : defaultValue
    );

    React.useEffect(() => {
      if (value !== undefined) {
        setSelectedValue(value);
      }
    }, [value]);

    const handleRadioChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      if (disabled) return;
      const val = e.target.value;
      if (value === undefined) {
        setSelectedValue(val);
      }
      if (onChange) {
        onChange(val);
      }
    };

    return (
      <div
        ref={ref}
        role="radiogroup"
        aria-label={label}
        className={cn('flex flex-col gap-2', className)}
        {...props}
      >
        {label && (
          <span className="text-sm font-medium text-foreground select-none" data-testid="radiogroup-label">
            {label}
          </span>
        )}

        <div
          className={cn(
            'flex gap-4',
            orientation === 'vertical' ? 'flex-col' : 'flex-row flex-wrap'
          )}
        >
          {options.map((option) => {
            const optionId = `radio-${name}-${option.value}`;
            const isChecked = selectedValue === option.value;
            const isOptionDisabled = disabled || option.disabled;

            return (
              <label
                key={option.value}
                htmlFor={optionId}
                className={cn(
                  'inline-flex items-center gap-2.5 cursor-pointer select-none text-sm font-medium text-foreground',
                  isOptionDisabled && 'cursor-not-allowed opacity-50'
                )}
              >
                <div className="relative flex items-center h-5">
                  <input
                    id={optionId}
                    type="radio"
                    name={name}
                    value={option.value}
                    checked={isChecked}
                    disabled={isOptionDisabled}
                    onChange={handleRadioChange}
                    className="sr-only peer"
                  />
                  <div
                    className={cn(
                      'h-4 w-4 shrink-0 rounded-full border border-input bg-background flex items-center justify-center transition-all peer-focus-visible:outline-none peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-checked:border-primary peer-checked:bg-primary peer-checked:text-primary-foreground',
                      error && 'border-destructive peer-focus-visible:ring-destructive'
                    )}
                    data-testid={`radio-indicator-${option.value}`}
                  >
                    <div
                      className={cn(
                        'h-1.5 w-1.5 rounded-full bg-background transition-transform scale-0 peer-checked:scale-100',
                        isChecked && 'scale-100'
                      )}
                      data-testid={`radio-bullet-${option.value}`}
                    />
                  </div>
                </div>
                <span data-testid={`radio-label-${option.value}`}>{option.label}</span>
              </label>
            );
          })}
        </div>

        {error && (
          <p className="text-xs font-medium text-destructive mt-0.5" data-testid="radiogroup-error">
            {error}
          </p>
        )}
      </div>
    );
  }
);

RadioGroup.displayName = 'RadioGroup';

import * as React from 'react';
import { Input } from './Input';
import { cn } from '../../utils/cn';

export interface PhoneInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type' | 'prefix'> {
  label?: string;
  error?: string;
  helperText?: string;
  showCountryCode?: boolean;
  countryCode?: string;
  fullWidth?: boolean;
}

export const PhoneInput = React.forwardRef<HTMLInputElement, PhoneInputProps>(
  (
    {
      className,
      value,
      defaultValue,
      onChange,
      showCountryCode = true,
      countryCode = '+91',
      ...props
    },
    ref
  ) => {
    const [displayVal, setDisplayVal] = React.useState('');

    const formatPhone = (val: string) => {
      const digits = val.replace(/\D/g, '').slice(0, 10);
      if (digits.length <= 5) return digits;
      return `${digits.slice(0, 5)} ${digits.slice(5)}`;
    };

    // Sync prop value
    React.useEffect(() => {
      if (value !== undefined) {
        setDisplayVal(formatPhone(String(value)));
      }
    }, [value]);

    // Initial binding if uncontrolled
    React.useEffect(() => {
      if (value === undefined && defaultValue !== undefined) {
        setDisplayVal(formatPhone(String(defaultValue)));
      }
    }, [defaultValue, value]);

    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const inputStr = e.target.value;
      const formatted = formatPhone(inputStr);
      
      setDisplayVal(formatted);

      if (onChange) {
        // Construct a synthetic change event to maintain compatibility with React Hook Form
        const syntheticEvent = {
          ...e,
          target: {
            ...e.target,
            value: formatted,
            name: e.target.name,
          },
        };
        onChange(syntheticEvent as any);
      }
    };

    return (
      <Input
        ref={ref}
        type="tel"
        value={displayVal}
        onChange={handleChange}
        prefix={
          showCountryCode ? (
            <span className="text-sm font-medium text-muted-foreground select-none" data-testid="phone-country-code">
              {countryCode}
            </span>
          ) : undefined
        }
        placeholder="98765 43210"
        className={cn(className)}
        {...props}
      />
    );
  }
);

PhoneInput.displayName = 'PhoneInput';

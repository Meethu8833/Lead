import * as React from 'react';
import { Input } from './Input';
import { Spinner } from './Spinner';
import { Search, X } from 'lucide-react';
import { useDebounce } from '../../hooks/ui-hooks';
import { cn } from '../../utils/cn';

export interface SearchBoxProps
  extends Omit<
    React.InputHTMLAttributes<HTMLInputElement>,
    'onChange' | 'value' | 'defaultValue' | 'prefix' | 'suffix'
  > {
  value?: string;
  defaultValue?: string;
  onSearch: (value: string) => void;
  debounceDelay?: number;
  isLoading?: boolean;
  label?: string;
  error?: string;
  helperText?: string;
  showShortcut?: boolean;
}

export const SearchBox = React.forwardRef<HTMLInputElement, SearchBoxProps>(
  (
    {
      className,
      value,
      defaultValue,
      onSearch,
      debounceDelay = 300,
      isLoading = false,
      showShortcut = true,
      ...props
    },
    ref
  ) => {
    const [searchTerm, setSearchTerm] = React.useState(
      value !== undefined ? value : defaultValue || ''
    );

    const inputRef = React.useRef<HTMLInputElement>(null);
    React.useImperativeHandle(ref, () => inputRef.current!);

    // Debounce the input term
    const debouncedTerm = useDebounce(searchTerm, debounceDelay);
    const lastCalledRef = React.useRef(debouncedTerm);

    // Sync external value updates
    React.useEffect(() => {
      if (value !== undefined) {
        setSearchTerm(value);
      }
    }, [value]);

    // Handle debounced search execution
    React.useEffect(() => {
      if (debouncedTerm !== lastCalledRef.current) {
        lastCalledRef.current = debouncedTerm;
        onSearch(debouncedTerm);
      }
    }, [debouncedTerm, onSearch]);

    // Register global shortcuts
    React.useEffect(() => {
      if (!showShortcut) return;

      const handleKeyDown = (e: KeyboardEvent) => {
        const activeTag = document.activeElement?.tagName;
        const isEditing =
          activeTag === 'INPUT' ||
          activeTag === 'TEXTAREA' ||
          document.activeElement?.getAttribute('contenteditable') === 'true';

        if (isEditing) return;

        if (e.key === '/') {
          e.preventDefault();
          inputRef.current?.focus();
        } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
          e.preventDefault();
          inputRef.current?.focus();
        }
      };

      window.addEventListener('keydown', handleKeyDown);
      return () => window.removeEventListener('keydown', handleKeyDown);
    }, [showShortcut]);

    const handleClear = () => {
      setSearchTerm('');
      inputRef.current?.focus();
      // Instantly fire search when cleared
      onSearch('');
    };

    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      setSearchTerm(e.target.value);
    };

    const searchIcon = (
      <Search className="h-4 w-4 text-muted-foreground" data-testid="search-icon" />
    );

    const suffixAction = (
      <div className="flex items-center gap-1.5" data-testid="search-suffix-container">
        {isLoading ? (
          <Spinner size="sm" data-testid="search-loading" />
        ) : searchTerm ? (
          <button
            type="button"
            onClick={handleClear}
            className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring transition-colors"
            aria-label="Clear search"
            data-testid="search-clear"
          >
            <X className="h-4 w-4" />
          </button>
        ) : showShortcut ? (
          <kbd
            className="pointer-events-none hidden sm:inline-flex h-5 select-none items-center gap-1 rounded border border-input bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground"
            data-testid="search-kbd"
          >
            /
          </kbd>
        ) : null}
      </div>
    );

    return (
      <Input
        ref={inputRef}
        type="search"
        value={searchTerm}
        onChange={handleChange}
        prefix={searchIcon}
        suffix={suffixAction}
        className={cn('pr-12', className)}
        {...props}
      />
    );
  }
);

SearchBox.displayName = 'SearchBox';

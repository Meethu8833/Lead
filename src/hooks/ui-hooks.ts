import { useState, useEffect } from 'react';

/**
 * Custom hook to debounce a value change.
 *
 * @template T - The type of the value to debounce.
 * @param value - The value to debounce.
 * @param delay - The debounce delay in milliseconds.
 * @returns The debounced value.
 */
export function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);

  return debouncedValue;
}

/**
 * Pagination state manager hook.
 */
interface UsePaginationReturn {
  page: number;
  pageSize: number;
  totalPages: number;
  setPage: (page: number) => void;
  setPageSize: (size: number) => void;
  next: () => void;
  previous: () => void;
  first: () => void;
  last: () => void;
  canNext: boolean;
  canPrevious: boolean;
  startIndex: number;
  endIndex: number;
}

/**
 * Custom hook to manage pagination state (compatible with client and server pagination).
 *
 * @param totalItems - The total count of items.
 * @param initialPageSize - The page size (default: 10).
 * @returns Pagination states and actions.
 */
export function usePagination(
  totalItems: number,
  initialPageSize: number = 10
): UsePaginationReturn {
  const [page, setPageInternal] = useState(1);
  const [pageSize, setPageSizeInternal] = useState(initialPageSize);

  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));

  // Ensure page stays within bounds when totalItems or pageSize changes
  useEffect(() => {
    if (page > totalPages) {
      setPageInternal(totalPages);
    }
  }, [totalItems, pageSize, totalPages, page]);

  const setPage = (newPage: number) => {
    const boundedPage = Math.max(1, Math.min(newPage, totalPages));
    setPageInternal(boundedPage);
  };

  const setPageSize = (size: number) => {
    const nextSize = Math.max(1, size);
    setPageSizeInternal(nextSize);
  };

  const next = () => setPage(page + 1);
  const previous = () => setPage(page - 1);
  const first = () => setPage(1);
  const last = () => setPage(totalPages);

  const canNext = page < totalPages;
  const canPrevious = page > 1;

  const startIndex = (page - 1) * pageSize;
  const endIndex = Math.min(startIndex + pageSize, totalItems);

  return {
    page,
    pageSize,
    totalPages,
    setPage,
    setPageSize,
    next,
    previous,
    first,
    last,
    canNext,
    canPrevious,
    startIndex,
    endIndex,
  };
}

/**
 * Custom hook to sync state with localStorage.
 *
 * @template T - The type of the state value.
 * @param key - The localStorage key name.
 * @param initialValue - The fallback initial value.
 * @returns A tuple of state value and value setter.
 */
export function useLocalStorage<T>(
  key: string,
  initialValue: T
): readonly [T, (value: T | ((val: T) => T)) => void] {
  const [storedValue, setStoredValue] = useState<T>(() => {
    if (typeof window === 'undefined') {
      return initialValue;
    }
    try {
      const item = window.localStorage.getItem(key);
      if (item) {
        try {
          return JSON.parse(item) as T;
        } catch {
          // Malformed JSON recovery
          return initialValue;
        }
      }
      return initialValue;
    } catch (error) {
      console.error('Error reading localStorage key:', key, error);
      return initialValue;
    }
  });

  const setValue = (value: T | ((val: T) => T)) => {
    try {
      const valueToStore = value instanceof Function ? value(storedValue) : value;
      setStoredValue(valueToStore);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(key, JSON.stringify(valueToStore));
      }
    } catch (error) {
      console.error('Error setting localStorage key:', key, error);
    }
  };

  return [storedValue, setValue] as const;
}

/**
 * Custom hook to detect window media query match states.
 *
 * @param query - The media query string (e.g. '(max-width: 768px)').
 * @returns Boolean flag indicating if media query matches.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined') {
      return false;
    }
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const mediaQueryList = window.matchMedia(query);
    const listener = (event: MediaQueryListEvent) => {
      setMatches(event.matches);
    };

    if (mediaQueryList.addEventListener) {
      mediaQueryList.addEventListener('change', listener);
    } else {
      // Deprecated addListener support for older agents/browsers
      mediaQueryList.addListener(listener);
    }

    // Set initial state
    setMatches(mediaQueryList.matches);

    return () => {
      if (mediaQueryList.removeEventListener) {
        mediaQueryList.removeEventListener('change', listener);
      } else {
        mediaQueryList.removeListener(listener);
      }
    };
  }, [query]);

  return matches;
}

/**
 * Options for useConfirmation dialog triggers.
 */
interface ConfirmationOptions {
  title: string;
  description: string;
}

/**
 * Custom hook to manage Promise-based confirmation flows.
 *
 * Useful for powering reusable ConfirmationDialog popups.
 */
export function useConfirmation() {
  const [state, setState] = useState<{
    isOpen: boolean;
    title: string;
    description: string;
    resolve: ((value: boolean) => void) | null;
  }>({
    isOpen: false,
    title: '',
    description: '',
    resolve: null,
  });

  const confirm = (options: ConfirmationOptions): Promise<boolean> => {
    return new Promise<boolean>((resolve) => {
      setState({
        isOpen: true,
        title: options.title,
        description: options.description,
        resolve,
      });
    });
  };

  const handleConfirm = () => {
    if (state.resolve) {
      state.resolve(true);
    }
    setState((prev) => ({ ...prev, isOpen: false, resolve: null }));
  };

  const handleCancel = () => {
    if (state.resolve) {
      state.resolve(false);
    }
    setState((prev) => ({ ...prev, isOpen: false, resolve: null }));
  };

  return {
    confirm,
    resolve: handleConfirm,
    reject: handleCancel,
    isOpen: state.isOpen,
    title: state.title,
    description: state.description,
  };
}

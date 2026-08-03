import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { cn } from '../utils/cn';
import {
  formatCurrency,
  formatDate,
  formatDateTime,
  formatPhone,
  truncate,
  copyToClipboard,
} from '../utils/helpers';
import {
  useDebounce,
  usePagination,
  useLocalStorage,
  useMediaQuery,
} from '../hooks/ui-hooks';

// ==========================================
// UTILITY TESTS
// ==========================================

describe('cn utility', () => {
  it('combines and merges Tailwind classes resolving conflicts', () => {
    expect(cn('px-2 py-1', 'p-4')).toBe('p-4');
    expect(cn('bg-red-500', 'bg-blue-500')).toBe('bg-blue-500');
    expect(cn('text-sm font-bold', 'text-lg')).toBe('font-bold text-lg');
  });

  it('handles conditional classes correctly', () => {
    expect(cn('btn', true && 'btn-active', false && 'btn-hidden')).toBe('btn btn-active');
    expect(cn('p-4', null, undefined, '', 'm-2')).toBe('p-4 m-2');
  });
});

describe('helper functions', () => {
  describe('formatCurrency', () => {
    it('formats values in Indian Rupees (INR) format by default', () => {
      // Note: NBSP (\u00a0) is sometimes used in format outputs. We clean whitespace for easier comparisons.
      const formatted = formatCurrency(123456.78).replace(/\u00a0/g, ' ');
      expect(formatted).toContain('1,23,456.78');
      expect(formatted).toContain('₹');
    });

    it('supports custom currency configurations', () => {
      const formatted = formatCurrency(1234.56, 'USD').replace(/\u00a0/g, ' ');
      expect(formatted).toContain('1,234.56');
      expect(formatted).toContain('$');
    });

    it('safely handles null and undefined inputs', () => {
      expect(formatCurrency(null)).toBe('-');
      expect(formatCurrency(undefined)).toBe('-');
    });
  });

  describe('formatDate', () => {
    it('formats Dates and date strings to YYYY-MM-DD', () => {
      const dateObj = new Date('2026-08-02T12:00:00Z');
      expect(formatDate(dateObj)).toBe('2026-08-02');
      expect(formatDate('2026-05-15')).toBe('2026-05-15');
    });

    it('safely handles null, undefined, and invalid inputs', () => {
      expect(formatDate(null)).toBe('-');
      expect(formatDate(undefined)).toBe('-');
      expect(formatDate('invalid-date')).toBe('-');
    });
  });

  describe('formatDateTime', () => {
    it('formats Dates and date strings to YYYY-MM-DD HH:mm', () => {
      const dateObj = new Date('2026-08-02T17:30:00');
      // Format uses local timezone, let's parse a specific formatted output or format a known datejs output
      const expectedDate = formatDate(dateObj); // YYYY-MM-DD
      const formatted = formatDateTime(dateObj);
      expect(formatted).toContain(expectedDate);
      expect(formatted).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
    });

    it('safely handles null, undefined, and invalid inputs', () => {
      expect(formatDateTime(null)).toBe('-');
      expect(formatDateTime(undefined)).toBe('-');
      expect(formatDateTime('invalid-date')).toBe('-');
    });
  });

  describe('formatPhone', () => {
    it('formats 10-digit number strings or numbers as XXXXX XXXXX', () => {
      expect(formatPhone('9876543210')).toBe('98765 43210');
      expect(formatPhone(9876543210)).toBe('98765 43210');
    });

    it('returns the input unmodified if it is not 10 digits', () => {
      expect(formatPhone('12345')).toBe('12345');
      expect(formatPhone('123456789012')).toBe('123456789012');
    });

    it('safely handles null, undefined, and empty inputs', () => {
      expect(formatPhone(null)).toBe('-');
      expect(formatPhone(undefined)).toBe('-');
      expect(formatPhone('   ')).toBe('-');
    });
  });

  describe('truncate', () => {
    it('truncates strings longer than the specified length', () => {
      expect(truncate('Hello World', 5)).toBe('Hello...');
    });

    it('returns the full string if it is shorter than or equal to length', () => {
      expect(truncate('Hello', 5)).toBe('Hello');
      expect(truncate('Hello', 10)).toBe('Hello');
    });

    it('handles empty, null, or undefined values gracefully', () => {
      expect(truncate(null, 5)).toBe('');
      expect(truncate(undefined, 5)).toBe('');
      expect(truncate('', 5)).toBe('');
    });
  });

  describe('copyToClipboard', () => {
    it('copies text via clipboard API when available', async () => {
      const writeTextMock = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: writeTextMock },
        writable: true,
      });
      Object.defineProperty(window, 'isSecureContext', {
        value: true,
        writable: true,
      });

      const success = await copyToClipboard('test-text');
      expect(success).toBe(true);
      expect(writeTextMock).toHaveBeenCalledWith('test-text');
    });
  });
});

// ==========================================
// HOOK TESTS
// ==========================================

describe('useDebounce hook', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('delays updating value until timeout', () => {
    const { result, rerender } = renderHook(
      ({ value, delay }) => useDebounce(value, delay),
      { initialProps: { value: 'first', delay: 300 } }
    );

    expect(result.current).toBe('first');

    // Trigger update
    rerender({ value: 'second', delay: 300 });
    expect(result.current).toBe('first'); // Still first

    // Advance halfway
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(result.current).toBe('first');

    // Advance fully
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(result.current).toBe('second');
  });
});

describe('usePagination hook', () => {
  it('calculates boundaries and limits', () => {
    const { result } = renderHook(() => usePagination(25, 10));
    
    expect(result.current.page).toBe(1);
    expect(result.current.pageSize).toBe(10);
    expect(result.current.totalPages).toBe(3);
    expect(result.current.canPrevious).toBe(false);
    expect(result.current.canNext).toBe(true);
    expect(result.current.startIndex).toBe(0);
    expect(result.current.endIndex).toBe(10);
  });

  it('performs paging actions correctly', () => {
    const { result } = renderHook(() => usePagination(25, 10));

    act(() => {
      result.current.next();
    });
    expect(result.current.page).toBe(2);
    expect(result.current.startIndex).toBe(10);
    expect(result.current.endIndex).toBe(20);
    expect(result.current.canPrevious).toBe(true);

    act(() => {
      result.current.last();
    });
    expect(result.current.page).toBe(3);
    expect(result.current.endIndex).toBe(25);
    expect(result.current.canNext).toBe(false);

    act(() => {
      result.current.previous();
    });
    expect(result.current.page).toBe(2);

    act(() => {
      result.current.first();
    });
    expect(result.current.page).toBe(1);
  });

  it('updates total pages when totalItems changes', () => {
    const { result, rerender } = renderHook(
      ({ totalItems }) => usePagination(totalItems, 10),
      { initialProps: { totalItems: 25 } }
    );

    expect(result.current.totalPages).toBe(3);

    rerender({ totalItems: 5 });
    expect(result.current.totalPages).toBe(1);
    expect(result.current.page).toBe(1); // Auto-adjusted
  });
});

describe('useLocalStorage hook', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('initializes and saves state values in localStorage', () => {
    const { result } = renderHook(() => useLocalStorage('theme-mode', 'dark'));
    expect(result.current[0]).toBe('dark');

    act(() => {
      result.current[1]('light');
    });

    expect(result.current[0]).toBe('light');
    expect(window.localStorage.getItem('theme-mode')).toBe(JSON.stringify('light'));
  });

  it('gracefully recovers when malformed JSON is found in storage', () => {
    window.localStorage.setItem('theme-mode', 'malformed-json-{-');
    const { result } = renderHook(() => useLocalStorage('theme-mode', 'system'));
    
    expect(result.current[0]).toBe('system');
  });
});

describe('useMediaQuery hook', () => {
  const originalMatchMedia = window.matchMedia;

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
  });

  it('responds to media query changes', () => {
    let listener: ((event: any) => void) | null = null;
    let mockMatches = false;

    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: mockMatches,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn().mockImplementation((event, cb) => {
        if (event === 'change') {
          listener = cb;
        }
      }),
      removeEventListener: vi.fn(),
    }));

    const { result } = renderHook(() => useMediaQuery('(max-width: 768px)'));
    expect(result.current).toBe(false);

    // Simulate match query event change
    act(() => {
      mockMatches = true;
      if (listener) {
        listener({ matches: true } as MediaQueryListEvent);
      }
    });

    expect(result.current).toBe(true);
  });
});

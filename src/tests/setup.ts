import '@testing-library/jest-dom';
import { vi } from 'vitest';

// Mock window.matchMedia since jsdom does not support it
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(), // deprecated
    removeListener: vi.fn(), // deprecated
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock console.error to avoid cluttering test outputs for expected failures
vi.spyOn(console, 'error').mockImplementation(() => {});

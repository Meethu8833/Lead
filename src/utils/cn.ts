import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Combines multiple class values and merges Tailwind CSS classes, resolving conflicts.
 *
 * @param inputs - Array of class names, conditional objects, or arrays of classes.
 * @returns A consolidated string of merged Tailwind CSS classes.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

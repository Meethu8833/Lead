import dayjs from 'dayjs';

/**
 * Formats a number as a currency string.
 *
 * @param value - The numeric value to format.
 * @param currency - The ISO currency code (default: 'INR').
 * @returns Formatted currency string, or '-' if input is null or undefined.
 */
export function formatCurrency(
  value: number | null | undefined,
  currency: string = 'INR'
): string {
  if (value === null || value === undefined) {
    return '-';
  }
  try {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency,
    }).format(value);
  } catch (error) {
    console.error('Error formatting currency:', error);
    return `${currency} ${value}`;
  }
}

/**
 * Formats a Date or date string to YYYY-MM-DD.
 *
 * @param date - The Date object or string to format.
 * @returns The formatted date string, or '-' if input is invalid or empty.
 */
export function formatDate(date: Date | string | null | undefined): string {
  if (!date) {
    return '-';
  }
  const parsed = dayjs(date);
  if (!parsed.isValid()) {
    return '-';
  }
  return parsed.format('YYYY-MM-DD');
}

/**
 * Formats a Date or date string to YYYY-MM-DD HH:mm.
 *
 * @param date - The Date object or string to format.
 * @returns The formatted date-time string, or '-' if input is invalid or empty.
 */
export function formatDateTime(date: Date | string | null | undefined): string {
  if (!date) {
    return '-';
  }
  const parsed = dayjs(date);
  if (!parsed.isValid()) {
    return '-';
  }
  return parsed.format('YYYY-MM-DD HH:mm');
}

/**
 * Formats a 10-digit phone number into "XXXXX XXXXX" format.
 *
 * @param value - The phone number string or number.
 * @returns Formatted phone number string, or the original value if invalid, or '-' if empty.
 */
export function formatPhone(value: string | number | null | undefined): string {
  if (value === null || value === undefined) {
    return '-';
  }
  const strVal = String(value).trim();
  if (!strVal) {
    return '-';
  }
  
  const cleaned = strVal.replace(/\D/g, '');
  if (cleaned.length === 10) {
    return `${cleaned.slice(0, 5)} ${cleaned.slice(5)}`;
  }
  return strVal;
}

/**
 * Truncates text to a specified length and appends an ellipsis.
 *
 * @param text - The text string to truncate.
 * @param length - The maximum length of the string before truncation.
 * @returns The truncated string, or an empty string if text is empty.
 */
export function truncate(text: string | null | undefined, length: number): string {
  if (!text) {
    return '';
  }
  if (text.length <= length) {
    return text;
  }
  return `${text.slice(0, length)}...`;
}

/**
 * Copies a string of text to the user's clipboard.
 *
 * @param text - The text content to copy.
 * @returns A promise that resolves to true if successful, false otherwise.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    
    // Fallback for older browsers or non-secure contexts
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-999999px';
    textArea.style.top = '-999999px';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    const successful = document.execCommand('copy');
    textArea.remove();
    return successful;
  } catch (error) {
    console.error('Failed to copy text to clipboard:', error);
    return false;
  }
}

/**
 * Downloads a file by creating a temporary anchor element.
 *
 * @param url - The source URL of the file to download.
 * @param filename - The target filename to trigger the download as.
 */
export function downloadFile(url: string, filename: string): void {
  if (typeof window === 'undefined') {
    return;
  }
  try {
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', filename);
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  } catch (error) {
    console.error('Failed to trigger file download:', error);
  }
}

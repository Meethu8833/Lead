// "Recently selected products" has no backend concept — it is a pure client-side UX nicety
// tracked in localStorage, scoped to this browser only.
const STORAGE_KEY = 'orders:recent-products';
const MAX_RECENT = 8;

export function getRecentProductIds(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function addRecentProductId(productId: string): void {
  try {
    const existing = getRecentProductIds().filter((id) => id !== productId);
    const next = [productId, ...existing].slice(0, MAX_RECENT);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // localStorage unavailable (private mode, SSR, storage full) — safe to no-op.
  }
}

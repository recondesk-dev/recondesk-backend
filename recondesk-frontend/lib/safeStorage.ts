/**
 * Safe browser storage utility.
 * Guarantees zero SSR hydration errors, handles private mode / disabled storage,
 * and catches JSON parsing / QuotaExceeded errors gracefully.
 */

export function safeStorageGet<T = unknown>(key: string, defaultValue: T): T {
  if (typeof window === "undefined") return defaultValue;
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === null) return defaultValue;
    return JSON.parse(raw) as T;
  } catch {
    return defaultValue;
  }
}

export function safeStorageGetString(key: string, defaultValue: string = ""): string {
  if (typeof window === "undefined") return defaultValue;
  try {
    const raw = window.localStorage.getItem(key);
    return raw !== null ? raw : defaultValue;
  } catch {
    return defaultValue;
  }
}

export function safeStorageSet(key: string, value: unknown): boolean {
  if (typeof window === "undefined") return false;
  try {
    const payload = typeof value === "string" ? value : JSON.stringify(value);
    window.localStorage.setItem(key, payload);
    return true;
  } catch (err) {
    console.warn(`[safeStorage] Failed to write key "${key}":`, err);
    return false;
  }
}

export function safeStorageRemove(key: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    window.localStorage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

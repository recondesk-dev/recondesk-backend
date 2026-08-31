const INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

/**
 * Starts a setInterval that pings /api/keepalive every 5 minutes so
 * Railway does not idle-sleep the backend container.
 *
 * Safe to call multiple times — only one interval is ever registered.
 * Must be called client-side only (typeof window !== "undefined").
 */
let started = false;

export function startKeepalive(): void {
  if (typeof window === "undefined") return;
  if (started) return;
  started = true;

  const ping = () => {
    fetch("/api/keepalive", { cache: "no-store" }).catch(() => {
      // Silently ignore — keepalive is best-effort.
    });
  };

  // Fire once immediately, then on every interval.
  ping();
  setInterval(ping, INTERVAL_MS);
}

/**
 * Native Browser Desktop Notification Utilities & Active Run Tracker.
 * Uses the HTML5 Web Notifications API (supported by Chrome, Safari, Edge, Firefox).
 */

export interface TrackedBackgroundRun {
  runId: string;
  clientId?: string;
  clientName: string;
  periodLabel?: string;
  startedAt: number;
}

const STORAGE_KEY = "recondesk_active_recon_runs";
const MAX_RUN_AGE_MS = 2 * 60 * 60 * 1000; // 2 hours

export function isNotificationSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

export function getNotificationPermission(): NotificationPermission | "unsupported" {
  if (!isNotificationSupported()) {
    return "unsupported";
  }
  return Notification.permission;
}

export async function requestNotificationPermission(): Promise<NotificationPermission | "unsupported"> {
  if (!isNotificationSupported()) {
    return "unsupported";
  }
  if (Notification.permission === "granted") {
    return "granted";
  }
  try {
    const result = await Notification.requestPermission();
    return result;
  } catch (err) {
    // Fallback for older callback-based browsers
    return new Promise((resolve) => {
      try {
        Notification.requestPermission((perm) => {
          resolve(perm);
        });
      } catch {
        resolve("unsupported");
      }
    });
  }
}

export interface ShowNotificationOptions {
  body?: string;
  icon?: string;
  tag?: string;
  onClickUrl?: string;
  onClick?: () => void;
}

export function showDesktopNotification(
  title: string,
  options?: ShowNotificationOptions
): Notification | null {
  if (!isNotificationSupported()) {
    return null;
  }
  if (Notification.permission !== "granted") {
    return null;
  }

  try {
    const notif = new Notification(title, {
      body: options?.body,
      icon: options?.icon ?? "/logo.png",
      tag: options?.tag,
    });

    notif.onclick = () => {
      try {
        window.focus();
      } catch {
        /* ignore */
      }
      if (options?.onClick) {
        options.onClick();
      } else if (options?.onClickUrl) {
        window.location.href = options.onClickUrl;
      }
      notif.close();
    };

    return notif;
  } catch (err) {
    console.warn("[desktopNotification] Failed to create Notification:", err);
    return null;
  }
}

/* ---------------- Active Background Run Tracker (localStorage) ---------------- */

export function getTrackedBackgroundRuns(): TrackedBackgroundRun[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];

    const now = Date.now();
    // Prune entries older than 2 hours
    const valid = parsed.filter(
      (r: TrackedBackgroundRun) =>
        r && typeof r.runId === "string" && now - (r.startedAt || 0) < MAX_RUN_AGE_MS
    );
    if (valid.length !== parsed.length) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(valid));
    }
    return valid;
  } catch {
    return [];
  }
}

export function trackBackgroundRun(run: TrackedBackgroundRun): void {
  if (typeof window === "undefined" || !run.runId) return;
  try {
    const runs = getTrackedBackgroundRuns().filter((r) => r.runId !== run.runId);
    runs.push(run);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(runs));
    // Dispatch a custom event so background notifier picks it up immediately
    window.dispatchEvent(new CustomEvent("recondesk:tracked_runs_updated"));
  } catch {
    /* ignore storage quota errors */
  }
}

export function untrackBackgroundRun(runId: string): void {
  if (typeof window === "undefined" || !runId) return;
  try {
    const runs = getTrackedBackgroundRuns().filter((r) => r.runId !== runId);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(runs));
    window.dispatchEvent(new CustomEvent("recondesk:tracked_runs_updated"));
  } catch {
    /* ignore */
  }
}

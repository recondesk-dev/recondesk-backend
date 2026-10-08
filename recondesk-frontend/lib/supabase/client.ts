import {
  clearCachedAuthRole,
  invalidateAuthProfileCache,
} from "@/lib/auth-profile";

/**
 * Legacy stub: Supabase has been 100% decommissioned in favor of AWS Cognito and Aurora.
 */
export function createClient(): any {
  return {
    auth: {
      getUser: async () => ({ data: { user: null }, error: new Error("Supabase decommissioned") }),
      getSession: async () => ({ data: { session: null }, error: null }),
      signOut: async () => ({ error: null }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe: () => {} } } }),
      resetPasswordForEmail: async () => ({ error: new Error("Use AWS Cognito") }),
      updateUser: async () => ({ error: new Error("Use AWS Cognito") }),
    },
    from: () => ({
      select: () => ({
        eq: () => ({
          maybeSingle: async () => ({ data: null, error: null }),
          single: async () => ({ data: null, error: null }),
          order: () => ({ range: async () => ({ data: [], error: null }) }),
        }),
        order: () => ({ range: async () => ({ data: [], error: null }) }),
      }),
      insert: async () => ({ data: null, error: null }),
      update: () => ({ eq: async () => ({ data: null, error: null }) }),
    }),
  };
}

const ACCESS_TOKEN_PATH = "/api/auth/access-token";

/**
 * Fetches the JWT via Route Handler using server-side Cognito HttpOnly cookie inspection.
 */
export async function fetchAccessTokenFromServer(): Promise<string | false> {
  try {
    let res = await fetch(ACCESS_TOKEN_PATH, {
      credentials: "same-origin",
      cache: "no-store",
    });

    // If unauthenticated (401), attempt a single Cognito refresh
    if (res.status === 401) {
      try {
        const refreshRes = await fetch("/api/auth/cognito-refresh", {
          method: "POST",
          credentials: "same-origin",
          cache: "no-store",
        });
        if (refreshRes.ok) {
          res = await fetch(ACCESS_TOKEN_PATH, {
            credentials: "same-origin",
            cache: "no-store",
          });
        }
      } catch {
        // Refresh failed; fail closed
      }
    }

    if (!res.ok) return false;
    const body = (await res.json()) as { access_token?: string | null };
    const t = body.access_token;
    return typeof t === "string" && t.length > 0 ? t : false;
  } catch {
    return false;
  }
}

export function purgeSupabaseLocalStorage(): void {
  if (typeof window === "undefined") return;
  try {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i);
      if (key && (key.startsWith("sb-") || key.includes("supabase"))) {
        localStorage.removeItem(key);
      }
    }
    for (let i = sessionStorage.length - 1; i >= 0; i--) {
      const key = sessionStorage.key(i);
      if (key && (key.startsWith("sb-") || key.includes("supabase"))) {
        sessionStorage.removeItem(key);
      }
    }
  } catch {
    // Ignore storage errors in private/sandboxed contexts
  }
}

/**
 * Subscribe to the JWT used for backend API calls.
 * Emits `string` when authenticated, or `false` when unauthenticated.
 * Source: AWS Cognito verified token via server HttpOnly cookies.
 */
const AUTH_TIMEOUT_MS = 5_000;

export function subscribeAccessToken(onToken: (accessToken: string | false) => void): () => void {
  let cancelled = false;
  let initialResolved = false;
  let lastEmitted: string | false | undefined;
  let safetyTimer: number | null = null;

  function emit(token: string | false) {
    if (cancelled) return;
    if (initialResolved && token === lastEmitted) return;
    initialResolved = true;
    lastEmitted = token;
    if (safetyTimer !== null) {
      window.clearTimeout(safetyTimer);
      safetyTimer = null;
    }
    onToken(token);
  }

  if (typeof window !== "undefined") {
    safetyTimer = window.setTimeout(() => {
      if (!initialResolved) {
        emit(false);
      }
    }, AUTH_TIMEOUT_MS);
  }

  async function resolveToken(): Promise<void> {
    if (cancelled) return;
    try {
      const fromServer = await fetchAccessTokenFromServer();
      if (cancelled) return;
      if (typeof fromServer === "string" && fromServer.length > 0) {
        purgeSupabaseLocalStorage();
        emit(fromServer);
        return;
      }
    } catch (err) {
      console.warn("[auth] fetchAccessTokenFromServer() error:", err);
    }

    if (cancelled) return;
    emit(false);
  }

  void resolveToken();

  const handleVisibility = () => {
    if (typeof document !== "undefined" && document.visibilityState === "visible") {
      void resolveToken();
    }
  };

  const handleFocus = () => {
    void resolveToken();
  };

  if (typeof window !== "undefined") {
    window.addEventListener("focus", handleFocus);
    document.addEventListener("visibilitychange", handleVisibility);
  }

  // Periodic refresh check every 4 minutes (Cognito access token lasts 1 hour)
  const interval = typeof window !== "undefined" ? window.setInterval(() => {
    void resolveToken();
  }, 240_000) : null;

  return () => {
    cancelled = true;
    if (safetyTimer !== null) window.clearTimeout(safetyTimer);
    if (interval !== null) window.clearInterval(interval);
    if (typeof window !== "undefined") {
      window.removeEventListener("focus", handleFocus);
      document.removeEventListener("visibilitychange", handleVisibility);
    }
  };
}

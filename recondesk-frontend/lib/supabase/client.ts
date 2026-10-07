import { createBrowserClient } from "@supabase/ssr";
import type { Database } from "@/lib/supabase/types";
import {
  clearCachedAuthRole,
  invalidateAuthProfileCache,
} from "@/lib/auth-profile";

/**
 * Browser-side Supabase client for Client Components.
 * Uses `createBrowserClient` from `@supabase/ssr` (not `createClient` from
 * `@supabase/supabase-js`) so PKCE + cookie storage matches middleware.
 */
export function createClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL?.trim() || "https://placeholder.supabase.co";
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY?.trim() || "placeholder-anon-key";
  return createBrowserClient<Database>(url, key);
}

const ACCESS_TOKEN_PATH = "/api/auth/access-token";

/**
 * Fetches the JWT via a Route Handler that uses `createServerClient` and
 * `cookies()` — the same session the dashboard server code sees. The browser
 * client often cannot read Supabase auth cookies (e.g. HttpOnly chunks), so
 * this is the reliable source for FastAPI `Authorization` headers.
 */
export async function fetchAccessTokenFromServer(): Promise<string | false> {
  try {
    let res = await fetch(ACCESS_TOKEN_PATH, {
      credentials: "same-origin",
      cache: "no-store",
    });

    // Dual-Auth Phase 2B: If unauthenticated (401), attempt a single Cognito refresh
    // to handle an expired Cognito access token.
    if (res.status === 401) {
      try {
        const refreshRes = await fetch("/api/auth/cognito-refresh", {
          method: "POST",
          credentials: "same-origin",
          cache: "no-store",
        });
        if (refreshRes.ok) {
          // Retry access token fetch once with refreshed cookies
          res = await fetch(ACCESS_TOKEN_PATH, {
            credentials: "same-origin",
            cache: "no-store",
          });
        }
      } catch {
        // Refresh failed; fail closed to unauthenticated
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
 *
 * Emits `string` when authenticated, or `false` once we know there is no session
 * (never emits `null` — use React `useState(null)` for "still resolving").
 *
 * Primary source: {@link fetchAccessTokenFromServer} (server reads cookies).
 * Secondary: `onAuthStateChange` when the browser client does see the session
 * (sign-in, refresh, sign-out in this tab).
 *
 * Safety guarantee: `onToken` is ALWAYS called within AUTH_TIMEOUT_MS even if
 * Supabase is unreachable or throws — preventing the UI from hanging forever.
 */
const AUTH_TIMEOUT_MS = 5_000;

export function subscribeAccessToken(onToken: (accessToken: string | false) => void): () => void {
  let cancelled = false;
  let initialResolved = false;
  let lastEmitted: string | false | undefined;
  let safetyTimer: number | null = null;

  function emit(token: string | false) {
    if (cancelled) return;
    // Skip duplicate emissions, but always allow the first resolution and
    // later TOKEN_REFRESHED / SIGNED_IN updates (stale JWTs caused 401s).
    if (initialResolved && token === lastEmitted) return;
    initialResolved = true;
    lastEmitted = token;
    if (safetyTimer !== null) {
      window.clearTimeout(safetyTimer);
      safetyTimer = null;
    }
    onToken(token);
  }

  const supabase = createClient();

  // Safety net: if the session resolution hangs (network error, Supabase
  // unreachable, environment misconfiguration), unblock the UI after timeout.
  if (typeof window !== "undefined") {
    safetyTimer = window.setTimeout(() => {
      if (!initialResolved) {
        console.warn("[auth] token resolution timed out after", AUTH_TIMEOUT_MS, "ms — emitting false");
        emit(false);
      }
    }, AUTH_TIMEOUT_MS);
  }

  async function resolveToken(): Promise<void> {
    if (cancelled) return;

    // 1. Check server-side route FIRST (reads Cognito HttpOnly cookies)
    try {
      const fromServer = await fetchAccessTokenFromServer();
      if (cancelled) return;
      if (typeof fromServer === "string" && fromServer.length > 0) {
        purgeSupabaseLocalStorage();
        emit(fromServer);
        return;
      }
    } catch (err) {
      console.warn("[auth] fetchAccessTokenFromServer() failed:", err);
    }

    // 2. Legacy fallback to Supabase browser session only if server returned no token
    try {
      const { data: sessionData } = await supabase.auth.getSession();
      if (cancelled) return;
      const token = sessionData.session?.access_token;
      if (token) {
        emit(token);
        return;
      }
    } catch (err) {
      console.warn("[auth] getSession() failed:", err);
    }

    if (cancelled) return;
    emit(false);
  }

  void resolveToken();

  const {
    data: { subscription },
  } = supabase.auth.onAuthStateChange((event, session) => {
    if (cancelled) return;
    if (event === "SIGNED_OUT") {
      clearCachedAuthRole();
      void invalidateAuthProfileCache();
      emit(false);
      return;
    }
    if (event === "SIGNED_IN" || event === "TOKEN_REFRESHED") {
      clearCachedAuthRole();
      void invalidateAuthProfileCache();
    }
    // Always resolve through server token first to ensure active Cognito session wins
    void resolveToken();
  });

  return () => {
    cancelled = true;
    if (safetyTimer !== null) window.clearTimeout(safetyTimer);
    subscription.unsubscribe();
  };
}

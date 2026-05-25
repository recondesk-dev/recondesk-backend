import { createBrowserClient } from "@supabase/ssr";
import type { Database } from "@/lib/supabase/types";

/**
 * Browser-side Supabase client for Client Components.
 * Uses `createBrowserClient` from `@supabase/ssr` (not `createClient` from
 * `@supabase/supabase-js`) so PKCE + cookie storage matches middleware.
 */
export function createClient() {
  return createBrowserClient<Database>(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );
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
    const res = await fetch(ACCESS_TOKEN_PATH, {
      credentials: "same-origin",
      cache: "no-store",
    });
    if (!res.ok) return false;
    const body = (await res.json()) as { access_token?: string | null };
    const t = body.access_token;
    return typeof t === "string" && t.length > 0 ? t : false;
  } catch {
    return false;
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
  let emitted = false;

  function emit(token: string | false) {
    if (emitted || cancelled) return;
    emitted = true;
    onToken(token);
  }

  const supabase = createClient();

  // Safety net: if the session resolution hangs (network error, Supabase
  // unreachable, environment misconfiguration), unblock the UI after timeout.
  const safetyTimer =
    typeof window !== "undefined"
      ? window.setTimeout(() => {
          if (!emitted) {
            console.warn("[auth] token resolution timed out after", AUTH_TIMEOUT_MS, "ms — emitting false");
            emit(false);
          }
        }, AUTH_TIMEOUT_MS)
      : null;

  async function resolveToken(): Promise<void> {
    if (cancelled || emitted) return;
    try {
      const { data: sessionData } = await supabase.auth.getSession();
      if (cancelled || emitted) return;
      const token = sessionData.session?.access_token;
      if (token) {
        emit(token);
        return;
      }
    } catch (err) {
      // Browser client threw (network error, bad config) — fall through to
      // the server-side route which reads HttpOnly session cookies.
      console.warn("[auth] getSession() failed, trying server route:", err);
      if (cancelled || emitted) return;
    }
    try {
      const fromServer = await fetchAccessTokenFromServer();
      if (cancelled || emitted) return;
      emit(typeof fromServer === "string" && fromServer.length > 0 ? fromServer : false);
    } catch (err) {
      console.warn("[auth] fetchAccessTokenFromServer() failed:", err);
      emit(false);
    }
  }

  void resolveToken();

  const {
    data: { subscription },
  } = supabase.auth.onAuthStateChange((event, session) => {
    if (cancelled) return;
    if (event === "SIGNED_OUT") {
      emit(false);
      return;
    }
    if (session?.access_token) {
      emit(session.access_token);
      return;
    }
    // INITIAL_SESSION or TOKEN_REFRESHED with no browser-visible session:
    // session may be in HttpOnly cookies — ask the server route.
    if (event === "INITIAL_SESSION" || event === "TOKEN_REFRESHED") {
      void resolveToken();
    }
  });

  return () => {
    cancelled = true;
    if (safetyTimer !== null) window.clearTimeout(safetyTimer);
    subscription.unsubscribe();
  };
}

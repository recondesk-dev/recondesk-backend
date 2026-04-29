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
 * (never emits `null` — use React `useState(null)` for “still resolving”).
 *
 * Primary source: {@link fetchAccessTokenFromServer} (server reads cookies).
 * Secondary: `onAuthStateChange` when the browser client does see the session
 * (sign-in, refresh, sign-out in this tab).
 */
export function subscribeAccessToken(onToken: (accessToken: string | false) => void): () => void {
  let cancelled = false;

  const syncFromServer = async () => {
    const t = await fetchAccessTokenFromServer();
    if (!cancelled) onToken(t);
  };

  void syncFromServer();

  const supabase = createClient();
  const {
    data: { subscription },
  } = supabase.auth.onAuthStateChange((event, session) => {
    if (cancelled) return;
    if (event === "SIGNED_OUT") {
      onToken(false);
      return;
    }
    if (session?.access_token) {
      onToken(session.access_token);
      return;
    }
    if (event === "INITIAL_SESSION" || event === "TOKEN_REFRESHED") {
      void syncFromServer();
    }
  });

  return () => {
    cancelled = true;
    subscription.unsubscribe();
  };
}

import { createClient } from "@supabase/supabase-js";
import type { Database } from "@/lib/supabase/types";

/**
 * Server-only Supabase admin client using the service role key.
 * Bypasses Row Level Security — use ONLY for trusted server-side operations
 * (e.g. crediting runs after a verified payment).
 *
 * NEVER import this in Client Components or expose it to the browser.
 * The service role key must be in SUPABASE_SERVICE_ROLE_KEY (no NEXT_PUBLIC_ prefix).
 */
export function createAdminClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL?.trim();
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY?.trim();

  if (!url || !serviceRoleKey) {
    throw new Error(
      "Missing NEXT_PUBLIC_SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY. " +
      "Add SUPABASE_SERVICE_ROLE_KEY to .env.local (and Vercel env vars)."
    );
  }

  return createClient<Database>(url, serviceRoleKey, {
    auth: {
      // Prevent the admin client from persisting any session — it acts as a
      // machine identity, not as a user.
      autoRefreshToken: false,
      persistSession: false,
    },
  });
}

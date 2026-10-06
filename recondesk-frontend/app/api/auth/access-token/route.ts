import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { createClient } from "@/lib/supabase/server";
import { COGNITO_COOKIE_NAMES } from "@/lib/cognito/cookies";
import { verifyCognitoAccessToken } from "@/lib/cognito/jwt";
import { resolveAccessTokenBridge } from "@/lib/cognito/sessionBridge";

/**
 * Returns the current user's access JWT using server-side cookie inspection.
 *
 * Dual-Auth Phase 2A Precedence:
 *   1. Valid Supabase session (provider="supabase")
 *   2. Valid Cognito access-token cookie (provider="cognito")
 *   3. 401 Unauthorized
 *
 * Precedence Rule (Requirement 5):
 * If both Supabase and Cognito sessions exist simultaneously, Supabase wins.
 * Reason: Supabase is current production auth and must not be broken or hijacked.
 *
 * Security:
 * - Refresh tokens are NEVER exposed to the browser.
 * - Cognito tokens are locally verified (RS256, issuer, client_id, exp, token_use=access).
 * - Fails closed to 401 if invalid/expired; never silently falls back.
 */
export async function GET(request: NextRequest) {
  const result = await resolveAccessTokenBridge({
    getSupabaseToken: async () => {
      const supabase = createClient();
      if (!supabase) return null;
      const {
        data: { session },
        error,
      } = await supabase.auth.getSession();
      if (error || !session?.access_token) return null;
      return session.access_token;
    },
    getCognitoCookie: () => {
      let token = request.cookies.get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)?.value;
      if (!token) {
        try {
          token = cookies().get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)?.value;
        } catch {
          // Non-request context
        }
      }
      return token;
    },
    verifyCognitoToken: async (token: string) => {
      await verifyCognitoAccessToken({ token });
    },
  });

  return NextResponse.json(result.body, { status: result.status });
}

import type { NextRequest } from "next/server";
import { cookies } from "next/headers";
import { COGNITO_COOKIE_NAMES } from "@/lib/cognito/cookies";
import { verifyCognitoAccessToken } from "@/lib/cognito/jwt";
import { createAdminClient } from "@/lib/supabase/admin";
import { resolveBillingCallerAuth, type AuthenticatedBillingUser } from "@/lib/cognito/sessionBridge";

export type AuthenticatedCognitoUser = AuthenticatedBillingUser;

/**
 * Authenticates a caller in Next.js Server Components and Route Handlers using Amazon Cognito.
 *
 * Checks:
 *   1. Authorization: Bearer <token> header (if request object is provided)
 *   2. HttpOnly Cognito session cookie (COGNITO_COOKIE_NAMES.ACCESS_TOKEN)
 *
 * Verifies RS256 signature, expiration, issuer, client_id, and token_use='access'.
 * Resolves the canonical ReconDesk user_profiles.id from cognito_user_mappings or user_profiles.
 */
export async function getAuthenticatedCognitoUser(
  request?: Request | NextRequest
): Promise<AuthenticatedCognitoUser | null> {
  const authHeader = request?.headers.get("authorization");

  let cookieToken: string | null | undefined;
  if (request && "cookies" in request && typeof (request as any).cookies?.get === "function") {
    cookieToken = (request as any).cookies.get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)?.value;
  }
  if (!cookieToken) {
    try {
      cookieToken = cookies().get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)?.value;
    } catch {
      // Non-cookies context
    }
  }
  if (!cookieToken && request) {
    const rawCookie = request.headers.get("cookie");
    if (rawCookie) {
      const match = rawCookie.match(new RegExp(`(?:^|;\\s*)${COGNITO_COOKIE_NAMES.ACCESS_TOKEN}=([^;]+)`));
      if (match) cookieToken = decodeURIComponent(match[1].trim());
    }
  }

  return resolveBillingCallerAuth({
    authHeader,
    cookieToken,
    verifyCognitoToken: async (token) => {
      const claims = await verifyCognitoAccessToken({ token });
      return {
        sub: claims.sub,
        email: typeof claims.email === "string" ? claims.email : undefined,
      };
    },
    lookupMapping: async (cognitoSub) => {
      try {
        const adminDb = createAdminClient();
        const { data: mapping } = await adminDb
          .from("cognito_user_mappings")
          .select("user_id, email, is_verified")
          .eq("cognito_sub", cognitoSub)
          .maybeSingle();

        if (mapping && (mapping as any).is_verified && (mapping as any).user_id) {
          return {
            userId: (mapping as any).user_id,
            email: (mapping as any).email,
          };
        }

        const { data: profile } = await adminDb
          .from("user_profiles")
          .select("id, email")
          .eq("id", cognitoSub)
          .maybeSingle();

        if (profile && (profile as any).id) {
          return {
            userId: (profile as any).id,
            email: (profile as any).email,
          };
        }
      } catch (err) {
        console.warn("[serverAuth] DB lookup failed:", err);
      }

      // Fallback to backend /api/v1/auth/me if DB didn't find mapping
      if (cookieToken || authHeader) {
        try {
          const tok = (authHeader ? authHeader.replace(/^Bearer\s+/i, "") : cookieToken) || "";
          const backendUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
          const res = await fetch(`${backendUrl}/api/v1/auth/me`, {
            headers: { Authorization: `Bearer ${tok}` },
            cache: "no-store",
          });
          if (res.ok) {
            const me = await res.json();
            if (me && me.id) {
              return {
                userId: me.id,
                email: me.email,
              };
            }
          }
        } catch (backendErr) {
          console.warn("[serverAuth] Backend /me fallback failed:", backendErr);
        }
      }

      return { userId: null };
    },
  });
}

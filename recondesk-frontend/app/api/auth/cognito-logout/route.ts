import { NextRequest, NextResponse } from "next/server";
import { getCognitoOAuthConfig } from "@/lib/cognito/oauth";
import {
  clearCognitoSessionCookies,
  clearCognitoHandshakeCookies,
} from "@/lib/cognito/cookies";
import { sanitizeRedirectPath } from "@/lib/cognito/pkce";

/**
 * Handles Cognito logout by terminating browser session cookies
 * and safely redirecting to an approved destination.
 *
 * Security:
 * - Clears access token, refresh token, and id token cookies.
 * - Clears any remaining OAuth handshake cookies (state, nonce, verifier).
 * - Restricts redirect destination to validated internal paths (anti-open redirect).
 * - Does not expose provider errors.
 */
export async function GET(request: NextRequest) {
  const config = getCognitoOAuthConfig();
  const searchParams = request.nextUrl.searchParams;

  const rawRedirect =
    searchParams.get("redirect") ||
    searchParams.get("redirect_to") ||
    searchParams.get("next") ||
    config.logoutUri ||
    "/login";

  let sanitizedDestination = "/login";
  try {
    if (rawRedirect.startsWith("http://") || rawRedirect.startsWith("https://")) {
      const parsed = new URL(rawRedirect);
      // If same-origin redirect, sanitize its pathname and search
      if (parsed.origin === request.nextUrl.origin) {
        sanitizedDestination = sanitizeRedirectPath(parsed.pathname + parsed.search, "/login");
      } else {
        // Fall back to /login for external URLs
        sanitizedDestination = "/login";
      }
    } else {
      sanitizedDestination = sanitizeRedirectPath(rawRedirect, "/login");
    }
  } catch {
    sanitizedDestination = "/login";
  }

  const targetUrl = new URL(sanitizedDestination, request.nextUrl.origin);
  const response = NextResponse.redirect(targetUrl);

  clearCognitoSessionCookies(response);
  clearCognitoHandshakeCookies(response);

  return response;
}

export async function POST(request: NextRequest) {
  const response = NextResponse.json({ status: "logged_out" }, { status: 200 });
  clearCognitoSessionCookies(response);
  clearCognitoHandshakeCookies(response);
  return response;
}

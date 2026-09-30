import type { NextResponse, NextRequest } from "next/server";

/**
 * Determines whether cookies must have the Secure flag set.
 * Requires Secure in production and HTTPS environments, but permits HTTP on localhost.
 */
export function isSecureCookie(protocol?: string): boolean {
  if (process.env.NODE_ENV === "production") return true;
  if (protocol === "https:" || protocol === "https") return true;
  return false;
}

/**
 * Centralized cookie names for Cognito OAuth handshake and authenticated session bridge.
 * (Dual-Auth Phase 2A)
 */
export const COGNITO_COOKIE_NAMES = {
  STATE: "recondesk_cognito_state",
  VERIFIER: "recondesk_cognito_pkce_verifier",
  NONCE: "recondesk_cognito_nonce",
  ACCESS_TOKEN: "recondesk_cognito_access_token",
  ID_TOKEN: "recondesk_cognito_id_token",
  REFRESH_TOKEN: "recondesk_cognito_refresh_token",
} as const;

/**
 * Default Cognito refresh token lifetime in seconds (30 days).
 */
export const DEFAULT_COGNITO_REFRESH_TOKEN_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

export interface SetCognitoSessionCookiesParams {
  accessToken: string;
  accessExp?: number; // JWT exp claim in seconds
  expiresIn?: number; // Token response expires_in in seconds
  refreshToken?: string;
  request?: NextRequest | null;
}

/**
 * Resolves whether session cookies should have the Secure flag set.
 * Enforces Secure in production and HTTPS environments, permitting HTTP on localhost dev.
 */
export function resolveCookieSecure(request?: NextRequest | null): boolean {
  if (process.env.NODE_ENV === "production") return true;
  if (!request) return isSecureCookie();
  const proto =
    request.nextUrl?.protocol ||
    request.headers.get("x-forwarded-proto") ||
    "";
  return isSecureCookie(proto ? (proto.endsWith(":") ? proto : `${proto}:`) : undefined);
}

/**
 * Sets server-only Cognito session cookies after verified trusted account mapping.
 *
 * Requirements (Phase 2A):
 *   - HttpOnly=true (no JavaScript access)
 *   - SameSite=Lax
 *   - Secure according to existing isSecureCookie() helper
 *   - Path="/"
 *   - Access-token expiry never exceeds token's real expiration
 *   - Refresh-token expiry follows configured Cognito refresh-token lifetime
 *   - ID token is deliberately NOT stored in cookies
 */
export function setCognitoSessionCookies(
  response: NextResponse,
  params: SetCognitoSessionCookiesParams
): void {
  const { accessToken, accessExp, expiresIn, refreshToken, request } = params;
  const secure = resolveCookieSecure(request);

  // Compute access token max-age strictly not exceeding token's real expiration
  const nowSec = Math.floor(Date.now() / 1000);
  let accessMaxAge = 3600; // default 1 hour fallback
  if (typeof accessExp === "number") {
    accessMaxAge = Math.max(0, accessExp - nowSec);
    if (typeof expiresIn === "number" && expiresIn > 0) {
      accessMaxAge = Math.min(accessMaxAge, expiresIn);
    }
  } else if (typeof expiresIn === "number" && expiresIn > 0) {
    accessMaxAge = expiresIn;
  }

  // 1. Set Access Token Cookie
  response.cookies.set(COGNITO_COOKIE_NAMES.ACCESS_TOKEN, accessToken, {
    httpOnly: true,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge: accessMaxAge,
  });

  // 2. Set Refresh Token Cookie ONLY if returned by Cognito
  if (refreshToken && refreshToken.trim().length > 0) {
    const configuredLifetime = parseInt(
      process.env.COGNITO_REFRESH_TOKEN_MAX_AGE_SECONDS || "",
      10
    );
    const refreshMaxAge =
      !isNaN(configuredLifetime) && configuredLifetime > 0
        ? configuredLifetime
        : DEFAULT_COGNITO_REFRESH_TOKEN_MAX_AGE_SECONDS;

    response.cookies.set(COGNITO_COOKIE_NAMES.REFRESH_TOKEN, refreshToken.trim(), {
      httpOnly: true,
      sameSite: "lax",
      secure,
      path: "/",
      maxAge: refreshMaxAge,
    });
  }

  // Deliberate security design: ID token is NOT stored as a cookie
}

/**
 * Clears Cognito session cookies (access token, refresh token, id token).
 */
export function clearCognitoSessionCookies(response: NextResponse): void {
  response.cookies.delete(COGNITO_COOKIE_NAMES.ACCESS_TOKEN);
  response.cookies.delete(COGNITO_COOKIE_NAMES.REFRESH_TOKEN);
  response.cookies.delete(COGNITO_COOKIE_NAMES.ID_TOKEN);
}

/**
 * Clears Cognito OAuth handshake cookies (state, nonce, pkce verifier).
 */
export function clearCognitoHandshakeCookies(response: NextResponse): void {
  response.cookies.delete(COGNITO_COOKIE_NAMES.STATE);
  response.cookies.delete(COGNITO_COOKIE_NAMES.NONCE);
  response.cookies.delete(COGNITO_COOKIE_NAMES.VERIFIER);
}

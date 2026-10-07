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
 * Resolves cookie domain for unified apex and subdomain access (.recondesk.in in production).
 */
export function resolveCookieDomain(request?: NextRequest | null): string | undefined {
  if (process.env.NODE_ENV !== "production") return undefined;
  if (!request) return ".recondesk.in";
  const host =
    request.headers.get("x-forwarded-host") ||
    request.nextUrl?.hostname ||
    request.headers.get("host") ||
    "";
  const cleanHost = host.split(":")[0].toLowerCase().trim();
  if (cleanHost.endsWith("recondesk.in")) {
    return ".recondesk.in";
  }
  return undefined;
}

/**
 * Sets server-only Cognito session cookies after verified trusted account mapping.
 *
 * Requirements (Phase 2A):
 *   - HttpOnly=true (no JavaScript access)
 *   - SameSite=Lax
 *   - Secure according to existing isSecureCookie() helper
 *   - Path="/"
 *   - Domain=".recondesk.in" when on recondesk.in
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
  const domain = resolveCookieDomain(request);

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

  const cookieOpts = {
    httpOnly: true,
    sameSite: "lax" as const,
    secure,
    path: "/",
    ...(domain ? { domain } : {}),
  };

  // 1. Set Access Token Cookie
  response.cookies.set(COGNITO_COOKIE_NAMES.ACCESS_TOKEN, accessToken, {
    ...cookieOpts,
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
      ...cookieOpts,
      maxAge: refreshMaxAge,
    });
  }

  // Deliberate security design: ID token is NOT stored as a cookie
}

/**
 * Clears Cognito session cookies (access token, refresh token, id token).
 */
export function clearCognitoSessionCookies(
  response: NextResponse,
  request?: NextRequest | null
): void {
  const domain = resolveCookieDomain(request);
  // Clear without domain (host-only)
  response.cookies.set(COGNITO_COOKIE_NAMES.ACCESS_TOKEN, "", { path: "/", maxAge: 0 });
  response.cookies.set(COGNITO_COOKIE_NAMES.REFRESH_TOKEN, "", { path: "/", maxAge: 0 });
  response.cookies.set(COGNITO_COOKIE_NAMES.ID_TOKEN, "", { path: "/", maxAge: 0 });
  // Clear with domain if present
  if (domain) {
    response.cookies.set(COGNITO_COOKIE_NAMES.ACCESS_TOKEN, "", { path: "/", maxAge: 0, domain });
    response.cookies.set(COGNITO_COOKIE_NAMES.REFRESH_TOKEN, "", { path: "/", maxAge: 0, domain });
    response.cookies.set(COGNITO_COOKIE_NAMES.ID_TOKEN, "", { path: "/", maxAge: 0, domain });
  }
  response.cookies.delete(COGNITO_COOKIE_NAMES.ACCESS_TOKEN);
  response.cookies.delete(COGNITO_COOKIE_NAMES.REFRESH_TOKEN);
  response.cookies.delete(COGNITO_COOKIE_NAMES.ID_TOKEN);
}

/**
 * Clears Cognito OAuth handshake cookies (state, nonce, pkce verifier).
 */
export function clearCognitoHandshakeCookies(
  response: NextResponse,
  request?: NextRequest | null
): void {
  const domain = resolveCookieDomain(request);
  const clearOpts = {
    path: "/",
    maxAge: 0,
    ...(domain ? { domain } : {}),
  };
  response.cookies.set(COGNITO_COOKIE_NAMES.STATE, "", clearOpts);
  response.cookies.set(COGNITO_COOKIE_NAMES.NONCE, "", clearOpts);
  response.cookies.set(COGNITO_COOKIE_NAMES.VERIFIER, "", clearOpts);
  response.cookies.delete(COGNITO_COOKIE_NAMES.STATE);
  response.cookies.delete(COGNITO_COOKIE_NAMES.NONCE);
  response.cookies.delete(COGNITO_COOKIE_NAMES.VERIFIER);
}

import { NextRequest, NextResponse } from "next/server";
import { getCognitoOAuthConfig, refreshCognitoTokens } from "@/lib/cognito/oauth";
import {
  COGNITO_COOKIE_NAMES,
  setCognitoSessionCookies,
  clearCognitoSessionCookies,
} from "@/lib/cognito/cookies";
import { verifyCognitoAccessToken } from "@/lib/cognito/jwt";

/**
 * Handles Cognito access-token refresh.
 *
 * Dual-Auth Phase 2B Security Workflow:
 * 1. Checks feature flag (fails closed if disabled).
 * 2. Reads HttpOnly Cognito refresh-token cookie server-side.
 * 3. Sends server-to-server token refresh request to Cognito token endpoint.
 * 4. Strictly validates returned access token (signature, issuer, client_id, exp, token_use=access).
 * 5. Rotates access-token cookie without exceeding token expiration.
 * 6. Rotates refresh-token cookie if a replacement was returned; otherwise retains existing cookie.
 * 7. On any failure: clears Cognito session cookies and returns 401 unauthenticated.
 * 8. Never exposes refresh tokens to the browser or in the response body.
 */
export async function POST(request: NextRequest) {
  const config = getCognitoOAuthConfig();
  if (!config.authEnabled) {
    return NextResponse.json(
      { error: "disabled", message: "Cognito authentication is disabled on this server." },
      { status: 501 }
    );
  }

  // 1. Read refresh-token cookie
  const refreshToken = request.cookies.get(COGNITO_COOKIE_NAMES.REFRESH_TOKEN)?.value;
  if (!refreshToken || refreshToken.trim().length === 0) {
    const response = NextResponse.json(
      { error: "unauthenticated", message: "Missing required refresh token." },
      { status: 401 }
    );
    clearCognitoSessionCookies(response);
    return response;
  }

  // 2. Perform server-side refresh request to Cognito
  let tokenResponse;
  try {
    tokenResponse = await refreshCognitoTokens({
      refreshToken: refreshToken.trim(),
      config,
    });
  } catch (err: unknown) {
    const detail = err instanceof Error ? err.message : "Provider refresh rejected";
    console.warn(`[Cognito Refresh] Provider refresh rejected: ${detail}`);
    const response = NextResponse.json(
      { error: "refresh_failed", message: "Unable to refresh session." },
      { status: 401 }
    );
    clearCognitoSessionCookies(response);
    return response;
  }

  if (!tokenResponse?.access_token) {
    const response = NextResponse.json(
      { error: "invalid_response", message: "Provider returned invalid token response." },
      { status: 401 }
    );
    clearCognitoSessionCookies(response);
    return response;
  }

  // 3. Strictly validate returned access token (signature, issuer, client_id, exp, token_use=access)
  let accessClaims;
  try {
    accessClaims = await verifyCognitoAccessToken({
      token: tokenResponse.access_token,
      config,
    });
  } catch (err: unknown) {
    const detail = err instanceof Error ? err.message : "Verification failed";
    console.warn(`[Cognito Refresh] Refreshed access token verification failed: ${detail}`);
    const response = NextResponse.json(
      { error: "invalid_token", message: "Refreshed access token failed verification." },
      { status: 401 }
    );
    clearCognitoSessionCookies(response);
    return response;
  }

  // 4. Rotate cookies and return safe response (never containing refresh token)
  const response = NextResponse.json(
    { status: "refreshed", provider: "cognito" },
    { status: 200 }
  );

  setCognitoSessionCookies(response, {
    accessToken: tokenResponse.access_token,
    accessExp: accessClaims.exp,
    expiresIn: tokenResponse.expires_in,
    // If Cognito returned a replacement refresh token, rotate it; otherwise retain existing
    refreshToken: tokenResponse.refresh_token,
    request,
  });

  return response;
}

export async function GET(request: NextRequest) {
  return POST(request);
}

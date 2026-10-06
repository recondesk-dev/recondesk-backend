import { NextRequest, NextResponse } from "next/server";
import {
  getCognitoOAuthConfig,
  exchangeCodeForTokens,
} from "@/lib/cognito/oauth";
import {
  COGNITO_COOKIE_NAMES,
  setCognitoSessionCookies,
  clearCognitoHandshakeCookies,
  clearCognitoSessionCookies,
} from "@/lib/cognito/cookies";
import {
  validateOAuthState,
  sanitizeRedirectPath,
} from "@/lib/cognito/pkce";
import {
  verifyCognitoIdToken,
  verifyCognitoAccessToken,
} from "@/lib/cognito/jwt";
import { lookupCognitoMapping } from "@/lib/cognito/mapping";

/**
 * Handles the OAuth 2.0 Authorization Code callback from Cognito.
 *
 * Hardened Security Workflow:
 *   1. Validates feature flag (fails closed if disabled).
 *   2. Validates OAuth state using timing-safe equality to defeat CSRF.
 *   3. Exchanges authorization code for tokens without leaking raw provider errors.
 *   4. Strictly verifies ID token signature, issuer, audience, expiration,
 *      token_use=id, and exact nonce match against stored login handshake.
 *   5. Strictly verifies Access token signature, issuer, client_id, expiration,
 *      and token_use=access.
 *   6. Sanitizes post-login redirect path (defeats open redirect exploits).
 *   7. Does NOT establish an authenticated ReconDesk session until trusted
 *      account mapping has been verified (Requirement 2).
 */
export async function GET(request: NextRequest) {
  const config = getCognitoOAuthConfig();
  if (!config.authEnabled) {
    return NextResponse.json(
      { error: "disabled", message: "Cognito authentication is disabled on this server." },
      { status: 501 }
    );
  }

  const searchParams = request.nextUrl.searchParams;
  const error = searchParams.get("error");

  // Reject raw error leakage to client
  if (error) {
    const redirectUrl = new URL("/login", request.nextUrl.origin);
    redirectUrl.searchParams.set("error", "auth_failed");
    const res = NextResponse.redirect(redirectUrl);
    clearCognitoHandshakeCookies(res);
    return res;
  }

  const rawState = searchParams.get("state");
  const code = searchParams.get("code");

  if (!rawState || !code) {
    const res = NextResponse.json(
      { error: "invalid_request", message: "Missing required authorization code or state parameter." },
      { status: 400 }
    );
    clearCognitoHandshakeCookies(res);
    return res;
  }

  // Parse state and extract post-login redirect destination
  let state = rawState;
  let rawNextPath = "/dashboard";
  if (rawState.includes(":")) {
    const parts = rawState.split(":", 2);
    state = parts[0];
    try {
      rawNextPath = decodeURIComponent(parts[1]) || "/dashboard";
    } catch {
      rawNextPath = "/dashboard";
    }
  }

  // Sanitize destination to reject external / protocol-relative redirects
  const sanitizedNextPath = sanitizeRedirectPath(rawNextPath, "/dashboard");

  // Retrieve stored handshake cookies
  const storedState = request.cookies.get(COGNITO_COOKIE_NAMES.STATE)?.value;
  const storedVerifier = request.cookies.get(COGNITO_COOKIE_NAMES.VERIFIER)?.value;
  const storedNonce = request.cookies.get(COGNITO_COOKIE_NAMES.NONCE)?.value;

  // Strict state validation (prevents CSRF)
  if (!validateOAuthState(state, storedState)) {
    const res = NextResponse.json(
      { error: "invalid_state", message: "Invalid or expired OAuth state parameter." },
      { status: 400 }
    );
    clearCognitoHandshakeCookies(res);
    return res;
  }

  if (!storedVerifier || !storedNonce) {
    const res = NextResponse.json(
      { error: "invalid_handshake", message: "Missing required PKCE verifier or login nonce cookie." },
      { status: 400 }
    );
    clearCognitoHandshakeCookies(res);
    return res;
  }

  // Exchange code for tokens (protecting credentials and suppressing raw provider errors)
  let tokenResponse;
  try {
    tokenResponse = await exchangeCodeForTokens({
      code,
      codeVerifier: storedVerifier,
      config,
    });
  } catch (err: unknown) {
    const detail = err instanceof Error ? err.message : "Unknown exchange failure";
    console.error(`[Cognito OAuth] Token exchange failed with provider: ${detail}`);
    const res = NextResponse.json(
      { error: "token_exchange_failed", message: "Unable to complete authentication with identity provider." },
      { status: 400 }
    );
    clearCognitoHandshakeCookies(res);
    return res;
  }

  if (!tokenResponse?.id_token || !tokenResponse?.access_token) {
    const res = NextResponse.json(
      { error: "invalid_token_response", message: "Identity provider response missing required tokens." },
      { status: 400 }
    );
    clearCognitoHandshakeCookies(res);
    return res;
  }

  // 1. Verify ID token signature, issuer, audience, expiration, token_use=id, and exact nonce
  let idClaims;
  try {
    idClaims = await verifyCognitoIdToken({
      token: tokenResponse.id_token,
      expectedNonce: storedNonce,
      config,
    });
  } catch (err: unknown) {
    const detail = err instanceof Error ? err.message : "Unknown verification error";
    console.error(`[Cognito OAuth] ID token verification failed: ${detail}`);
    const res = NextResponse.json(
      { error: "invalid_id_token", message: "Cognito ID token verification failed." },
      { status: 401 }
    );
    clearCognitoHandshakeCookies(res);
    return res;
  }

  // 2. Verify Access token signature, issuer, client_id, expiration, and token_use=access
  let accessClaims;
  try {
    accessClaims = await verifyCognitoAccessToken({
      token: tokenResponse.access_token,
      config,
    });
  } catch (err: unknown) {
    const detail = err instanceof Error ? err.message : "Unknown verification error";
    console.error(`[Cognito OAuth] Access token verification failed: ${detail}`);
    const res = NextResponse.json(
      { error: "invalid_access_token", message: "Cognito Access token verification failed." },
      { status: 401 }
    );
    clearCognitoHandshakeCookies(res);
    return res;
  }

  // 3. Trusted Cognito-to-Aurora identity mapping lookup via backend
  let mappingResult;
  try {
    mappingResult = await lookupCognitoMapping({
      accessToken: tokenResponse.access_token,
    });
  } catch (err: unknown) {
    const detail = err instanceof Error ? err.message : "Unknown lookup failure";
    console.warn(`[Cognito OAuth] Mapping lookup failed (failing closed): ${detail}`);
    mappingResult = {
      account_mapping_status: "pending_trusted_mapping_phase" as const,
      user_id: null,
    };
  }

  const isVerifiedFound =
    mappingResult.account_mapping_status === "verified_mapping_found" &&
    typeof mappingResult.user_id === "string" &&
    mappingResult.user_id.trim().length > 0;

  // Dual-Auth Phase 2A Session Bridge:
  // - Verified mapping found: Set server-only Cognito session cookies, clear handshake cookies, redirect to sanitized destination.
  // - Unmapped / pending mapping: Clear handshake and session cookies, redirect to safe unlinked error notice without exposing IDs.
  if (isVerifiedFound) {
    const redirectUrl = new URL(sanitizedNextPath, request.nextUrl.origin);
    const response = NextResponse.redirect(redirectUrl);
    setCognitoSessionCookies(response, {
      accessToken: tokenResponse.access_token,
      accessExp: accessClaims.exp,
      expiresIn: tokenResponse.expires_in,
      refreshToken: tokenResponse.refresh_token,
      request,
    });
    clearCognitoHandshakeCookies(response);
    return response;
  }

  // Unmapped identity: fail closed with no session cookies established
  const loginRedirectUrl = new URL("/login", request.nextUrl.origin);
  loginRedirectUrl.searchParams.set("error", "account_not_linked");
  const response = NextResponse.redirect(loginRedirectUrl);
  clearCognitoHandshakeCookies(response);
  clearCognitoSessionCookies(response);
  return response;
}

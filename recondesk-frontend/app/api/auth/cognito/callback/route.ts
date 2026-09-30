import { NextRequest, NextResponse } from "next/server";
import {
  getCognitoOAuthConfig,
  exchangeCodeForTokens,
  COGNITO_COOKIE_NAMES,
} from "@/lib/cognito/oauth";
import {
  validateOAuthState,
  sanitizeRedirectPath,
  isSecureCookie,
} from "@/lib/cognito/pkce";
import {
  verifyCognitoIdToken,
  verifyCognitoAccessToken,
} from "@/lib/cognito/jwt";

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
    return NextResponse.redirect(redirectUrl);
  }

  const rawState = searchParams.get("state");
  const code = searchParams.get("code");

  if (!rawState || !code) {
    return NextResponse.json(
      { error: "invalid_request", message: "Missing required authorization code or state parameter." },
      { status: 400 }
    );
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

  // Helper to clear handshake cookies
  const clearHandshakeCookies = (res: NextResponse) => {
    res.cookies.delete(COGNITO_COOKIE_NAMES.STATE);
    res.cookies.delete(COGNITO_COOKIE_NAMES.NONCE);
    res.cookies.delete(COGNITO_COOKIE_NAMES.VERIFIER);
  };

  // Strict state validation (prevents CSRF)
  if (!validateOAuthState(state, storedState)) {
    const res = NextResponse.json(
      { error: "invalid_state", message: "Invalid or expired OAuth state parameter." },
      { status: 400 }
    );
    clearHandshakeCookies(res);
    return res;
  }

  if (!storedVerifier || !storedNonce) {
    const res = NextResponse.json(
      { error: "invalid_handshake", message: "Missing required PKCE verifier or login nonce cookie." },
      { status: 400 }
    );
    clearHandshakeCookies(res);
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
    // Log safe diagnostic code without exposing raw response, codes, or secrets
    console.error("[Cognito OAuth] Token exchange failed with provider");
    const res = NextResponse.json(
      { error: "token_exchange_failed", message: "Unable to complete authentication with identity provider." },
      { status: 400 }
    );
    clearHandshakeCookies(res);
    return res;
  }

  if (!tokenResponse?.id_token || !tokenResponse?.access_token) {
    const res = NextResponse.json(
      { error: "invalid_token_response", message: "Identity provider response missing required tokens." },
      { status: 400 }
    );
    clearHandshakeCookies(res);
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
    console.error("[Cognito OAuth] ID token verification failed");
    const res = NextResponse.json(
      { error: "invalid_id_token", message: "Cognito ID token verification failed." },
      { status: 401 }
    );
    clearHandshakeCookies(res);
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
    console.error("[Cognito OAuth] Access token verification failed");
    const res = NextResponse.json(
      { error: "invalid_access_token", message: "Cognito Access token verification failed." },
      { status: 401 }
    );
    clearHandshakeCookies(res);
    return res;
  }

  // REQUIREMENT 2 & 10: Do NOT create an authenticated ReconDesk session until
  // the authenticated Cognito identity has been resolved through a trusted ReconDesk
  // account mapping. Keep the Cognito feature disabled until that mapping is implemented.
  const secure = isSecureCookie(request.nextUrl.protocol);

  // Return identity verification status without establishing an active ReconDesk session.
  // Persistent account mapping is kept as a separate migration phase.
  const response = NextResponse.json(
    {
      status: "identity_verified",
      cognito_sub: idClaims.sub,
      token_use: idClaims.token_use,
      access_token_use: accessClaims.token_use,
      account_mapping_status: "pending_trusted_mapping_phase",
      message: (
        "Cognito identity successfully verified. Active ReconDesk session creation " +
        "remains disabled until trusted Aurora account mapping is implemented."
      ),
      sanitized_next: sanitizedNextPath,
    },
    { status: 200 }
  );

  clearHandshakeCookies(response);
  return response;
}

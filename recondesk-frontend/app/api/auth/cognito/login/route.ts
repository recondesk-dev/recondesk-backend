import { NextRequest, NextResponse } from "next/server";
import {
  getCognitoOAuthConfig,
  buildCognitoAuthorizeUrl,
  COGNITO_COOKIE_NAMES,
} from "@/lib/cognito/oauth";
import {
  generateCodeVerifier,
  generateCodeChallenge,
  generateOAuthState,
  generateOAuthNonce,
  sanitizeRedirectPath,
  isSecureCookie,
} from "@/lib/cognito/pkce";

/**
 * Initiates the Cognito OAuth 2.0 Authorization Code Flow with PKCE.
 * Guarded by the COGNITO_AUTH_ENABLED feature flag.
 */
export async function GET(request: NextRequest) {
  const config = getCognitoOAuthConfig();
  if (!config.authEnabled) {
    return NextResponse.json(
      { error: "disabled", message: "Cognito authentication is disabled on this server." },
      { status: 501 }
    );
  }

  // Generate PKCE code verifier (high entropy secret) and code challenge (SHA256)
  const codeVerifier = generateCodeVerifier();
  const codeChallenge = generateCodeChallenge(codeVerifier);

  // Generate cryptographic state and nonce
  const state = generateOAuthState();
  const nonce = generateOAuthNonce();

  // Sanitize redirect path to prevent open redirect exploits
  const rawNext = request.nextUrl.searchParams.get("next");
  const sanitizedNext = sanitizeRedirectPath(rawNext, "/dashboard");
  const statePayload = `${state}:${encodeURIComponent(sanitizedNext)}`;

  const authorizeUrl = buildCognitoAuthorizeUrl({
    state: statePayload,
    nonce,
    codeChallenge,
    config,
  });

  const response = NextResponse.redirect(authorizeUrl);
  const secure = isSecureCookie(request.nextUrl.protocol);

  const cookieOptions = {
    httpOnly: true,
    sameSite: "lax" as const,
    secure,
    path: "/",
    maxAge: 300, // 5 minutes lifetime for handshake
  };

  response.cookies.set(COGNITO_COOKIE_NAMES.STATE, state, cookieOptions);
  response.cookies.set(COGNITO_COOKIE_NAMES.NONCE, nonce, cookieOptions);
  response.cookies.set(COGNITO_COOKIE_NAMES.VERIFIER, codeVerifier, cookieOptions);

  return response;
}

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

  let authorizeUrl: string;
  try {
    authorizeUrl = buildCognitoAuthorizeUrl({
      state: statePayload,
      nonce,
      codeChallenge,
      config,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Cognito configuration error.";
    return NextResponse.json(
      { error: "configuration_error", message },
      { status: 500 }
    );
  }

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

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  ""
);

/**
 * Handles direct email & password login with Cognito (with Supabase fallback).
 * Sets HttpOnly session cookies on success.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email, password } = body;
    if (!email || !password) {
      return NextResponse.json(
        { error: "bad_request", message: "Email and password are required.", detail: "Email and password are required." },
        { status: 400 }
      );
    }

    const backendRes = await fetch(`${API_URL}/api/v1/auth/cognito/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ email: email.trim(), password }),
      cache: "no-store",
    });

    const data = await backendRes.json().catch(() => null);

    if (!backendRes.ok) {
      const detail = data?.detail || data?.message || "Authentication failed";
      return NextResponse.json(
        {
          error: "auth_failed",
          detail,
          message: detail,
        },
        { status: backendRes.status }
      );
    }

    const response = NextResponse.json(
      {
        success: true,
        provider: data.provider || "cognito",
        user: data.user,
        access_token: data.access_token,
        refresh_token: data.refresh_token,
        expires_in: data.expires_in,
      },
      { status: 200 }
    );

    // If authenticated via Cognito, set server-only session cookies
    if (data.provider === "cognito" && data.access_token) {
      const { setCognitoSessionCookies } = await import("@/lib/cognito/cookies");
      setCognitoSessionCookies(response, {
        accessToken: data.access_token,
        expiresIn: data.expires_in,
        refreshToken: data.refresh_token,
        request,
      });
    }

    return response;
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Internal authentication error";
    return NextResponse.json(
      { error: "server_error", message: msg, detail: msg },
      { status: 500 }
    );
  }
}


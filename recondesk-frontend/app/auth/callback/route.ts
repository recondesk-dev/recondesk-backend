import { type NextRequest, NextResponse } from "next/server";

/**
 * Legacy Supabase auth callback route.
 * Redirects to the active Cognito OAuth callback route or login.
 * Supabase auth methods removed (100% Cognito Cutover).
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");

  if (code) {
    const cognitoCallback = new URL("/api/auth/cognito/callback", origin);
    searchParams.forEach((value, key) => {
      cognitoCallback.searchParams.set(key, value);
    });
    return NextResponse.redirect(cognitoCallback);
  }

  return NextResponse.redirect(new URL("/login", origin));
}

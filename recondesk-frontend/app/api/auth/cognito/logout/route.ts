import { NextRequest, NextResponse } from "next/server";
import { getCognitoOAuthConfig, COGNITO_COOKIE_NAMES } from "@/lib/cognito/oauth";

/**
 * Signs out of the Cognito session by clearing session cookies and redirecting to the sign-out URL.
 */
export async function GET(request: NextRequest) {
  const config = getCognitoOAuthConfig();
  const targetUrl = new URL(config.logoutUri || "/login", request.nextUrl.origin);
  const response = NextResponse.redirect(targetUrl);

  response.cookies.delete(COGNITO_COOKIE_NAMES.ACCESS_TOKEN);
  response.cookies.delete(COGNITO_COOKIE_NAMES.ID_TOKEN);
  response.cookies.delete(COGNITO_COOKIE_NAMES.REFRESH_TOKEN);
  response.cookies.delete(COGNITO_COOKIE_NAMES.STATE);
  response.cookies.delete(COGNITO_COOKIE_NAMES.NONCE);
  response.cookies.delete(COGNITO_COOKIE_NAMES.VERIFIER);

  return response;
}

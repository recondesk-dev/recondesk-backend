import { type NextRequest, NextResponse } from "next/server";

import {
  COGNITO_COOKIE_NAMES,
  setCognitoSessionCookies,
} from "@/lib/cognito/cookies";
import { verifyCognitoAccessToken } from "@/lib/cognito/jwt";
import { getCognitoOAuthConfig, refreshCognitoTokens } from "@/lib/cognito/oauth";

function passThrough(request: NextRequest) {
  return NextResponse.next({ request: { headers: request.headers } });
}

export async function middleware(request: NextRequest) {
  try {
    const pathname = request.nextUrl.pathname;

    // Legacy /onboarding route redirect directly to /dashboard
    if (pathname.startsWith("/onboarding")) {
      const url = request.nextUrl.clone();
      url.pathname = "/dashboard";
      url.search = "";
      return NextResponse.redirect(url);
    }

    const skipRedirect =
      pathname.startsWith("/login") ||
      pathname.startsWith("/signup") ||
      pathname.startsWith("/forgot-password") ||
      pathname.startsWith("/reset-password") ||
      pathname.startsWith("/auth") ||
      pathname.startsWith("/team/accept") ||
      pathname.startsWith("/api") ||
      pathname.startsWith("/_next") ||
      pathname === "/favicon.ico" ||
      /\.[a-zA-Z0-9]+$/.test(pathname);

    if (skipRedirect) {
      return passThrough(request);
    }

    let response = passThrough(request);
    let isAuthenticated = false;

    // 1. Check Cognito access token cookie (Primary AWS Auth)
    const cognitoToken = request.cookies.get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)?.value;
    if (cognitoToken && cognitoToken.trim().length > 0) {
      try {
        await verifyCognitoAccessToken({ token: cognitoToken.trim() });
        isAuthenticated = true;
      } catch (err: unknown) {
        const detail = err instanceof Error ? err.message : "Verification failed";
        console.warn(`[middleware] Cognito token verification failed: ${detail}`);
      }
    }

    // 2. If access token is expired or missing, attempt refresh using Cognito refresh-token cookie
    if (!isAuthenticated) {
      const refreshToken = request.cookies.get(COGNITO_COOKIE_NAMES.REFRESH_TOKEN)?.value;
      if (refreshToken && refreshToken.trim().length > 0) {
        try {
          const config = getCognitoOAuthConfig();
          if (config.authEnabled) {
            const tokenResponse = await refreshCognitoTokens({
              refreshToken: refreshToken.trim(),
              config,
            });
            if (tokenResponse?.access_token) {
              const claims = await verifyCognitoAccessToken({
                token: tokenResponse.access_token,
                config,
              });
              isAuthenticated = true;
              setCognitoSessionCookies(response, {
                accessToken: tokenResponse.access_token,
                accessExp: claims.exp,
                expiresIn: tokenResponse.expires_in,
                refreshToken: tokenResponse.refresh_token,
                request,
              });
            }
          }
        } catch (err: unknown) {
          const detail = err instanceof Error ? err.message : "Refresh failed";
          console.warn(`[middleware] Cognito refresh failed: ${detail}`);
        }
      }
    }

    if (!isAuthenticated) {
      const isProtectedRoute =
        pathname === "/welcome" ||
        pathname.startsWith("/dashboard") ||
        pathname.startsWith("/clients") ||
        pathname.startsWith("/reconcile") ||
        pathname.startsWith("/reconciliations") ||
        pathname.startsWith("/runs") ||
        pathname.startsWith("/billing") ||
        pathname.startsWith("/einvoicing") ||
        pathname.startsWith("/filing") ||
        pathname.startsWith("/manage-data") ||
        pathname.startsWith("/settings") ||
        pathname.startsWith("/vendors") ||
        pathname.startsWith("/upload");

      if (isProtectedRoute) {
        const url = request.nextUrl.clone();
        url.pathname = "/login";
        const redirectParam = pathname + request.nextUrl.search;
        if (redirectParam && redirectParam !== "/login" && redirectParam !== "/welcome") {
          url.searchParams.set("redirectTo", redirectParam);
        }
        return NextResponse.redirect(url);
      }
      return response;
    }

    // Root URL redirect check
    if (pathname === "/") {
      const url = request.nextUrl.clone();
      url.pathname = "/dashboard";
      url.search = "";
      return NextResponse.redirect(url);
    }

    return response;
  } catch {
    return passThrough(request);
  }
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};

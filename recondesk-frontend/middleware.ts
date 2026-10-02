import { type NextRequest, NextResponse } from "next/server";

import { COGNITO_COOKIE_NAMES } from "@/lib/cognito/cookies";
import { verifyCognitoAccessToken } from "@/lib/cognito/jwt";

function passThrough(request: NextRequest) {
  return NextResponse.next({ request: { headers: request.headers } });
}

export async function middleware(request: NextRequest) {
  try {
    const pathname = request.nextUrl.pathname;

    // If user lands on root or /reset-password with an auth code, route through /auth/callback to establish server session cookies
    if ((pathname === "/" || pathname === "/reset-password") && request.nextUrl.searchParams.has("code")) {
      const code = request.nextUrl.searchParams.get("code");
      const url = request.nextUrl.clone();
      url.pathname = "/auth/callback";
      url.searchParams.set("code", code!);
      url.searchParams.set("redirectTo", "/reset-password");
      return NextResponse.redirect(url);
    }

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
      pathname.startsWith("/auth") ||
      pathname.startsWith("/team") ||
      pathname.startsWith("/api") ||
      pathname.startsWith("/_next") ||
      pathname === "/favicon.ico" ||
      /\.[a-zA-Z0-9]+$/.test(pathname);

    if (skipRedirect) {
      return passThrough(request);
    }

    let isAuthenticated = false;

    // Amazon Cognito access-token cookie verification (100% Cognito Cutover)
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

    if (!isAuthenticated) {
      if (pathname === "/welcome") {
        const url = request.nextUrl.clone();
        url.pathname = "/login";
        return NextResponse.redirect(url);
      }
      return passThrough(request);
    }

    // Root URL redirect check
    if (pathname === "/") {
      const url = request.nextUrl.clone();
      url.pathname = "/dashboard";
      url.search = "";
      return NextResponse.redirect(url);
    }

    // NO ROUTE GUARD BLOCKS ACCESS TO THE REST OF THE APP.
    return passThrough(request);
  } catch {
    return passThrough(request);
  }
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};

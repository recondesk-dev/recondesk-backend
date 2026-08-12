import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

import {
  ONBOARDING_DONE_COOKIE,
  onboardingDoneCookieOptions,
} from "@/lib/onboarding-cookie";

/** Plain pass-through; use on errors so we never reuse a response that may be in a bad state. */
function passThrough(request: NextRequest) {
  return NextResponse.next({ request: { headers: request.headers } });
}

function withOnboardingCookie(response: NextResponse, userId: string): NextResponse {
  response.cookies.set(
    ONBOARDING_DONE_COOKIE,
    userId,
    onboardingDoneCookieOptions()
  );
  return response;
}

function redirectHomeToDashboard(request: NextRequest, response: NextResponse) {
  const pathname = request.nextUrl.pathname;
  if (pathname !== "/" && pathname !== "") {
    return response;
  }
  const url = request.nextUrl.clone();
  url.pathname = "/dashboard";
  url.search = "";
  const redirect = NextResponse.redirect(url);
  const done = response.cookies.get(ONBOARDING_DONE_COOKIE);
  if (done?.value) {
    redirect.cookies.set(
      ONBOARDING_DONE_COOKIE,
      done.value,
      onboardingDoneCookieOptions()
    );
  }
  return redirect;
}

export async function middleware(request: NextRequest) {
  try {
    const pathname = request.nextUrl.pathname;

    // Hard redirect /onboarding to /dashboard — onboarding page is completely removed
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

    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL?.trim();
    const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY?.trim();
    if (!supabaseUrl || !supabaseAnonKey) {
      return passThrough(request);
    }

    let response = passThrough(request);

    const supabase = createServerClient(supabaseUrl, supabaseAnonKey, {
      cookies: {
        get(name: string) {
          return request.cookies.get(name)?.value;
        },
        set(name: string, value: string, options: CookieOptions) {
          request.cookies.set({ name, value, ...options });
          response = passThrough(request);
          response.cookies.set({ name, value, ...options });
        },
        remove(name: string, options: CookieOptions) {
          request.cookies.set({ name, value: "", ...options });
          response = passThrough(request);
          response.cookies.set({ name, value: "", ...options });
        },
      },
    });

    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) {
      return response;
    }

    // Authenticated user: always mark onboarding done & redirect home to /dashboard
    response = withOnboardingCookie(response, user.id);
    return redirectHomeToDashboard(request, response);
  } catch {
    return passThrough(request);
  }
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};

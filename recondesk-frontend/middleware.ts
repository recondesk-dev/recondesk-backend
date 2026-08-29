import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

import {
  ONBOARDING_DONE_COOKIE,
  onboardingDoneCookieOptions,
} from "@/lib/onboarding-cookie";

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
      if (pathname === "/welcome") {
        const url = request.nextUrl.clone();
        url.pathname = "/login";
        return NextResponse.redirect(url);
      }
      return response;
    }

    response = withOnboardingCookie(response, user.id);

    // Root URL redirect check
    if (pathname === "/") {
      try {
        const { data: profile } = await supabase
          .from("user_profiles")
          .select("showcase_seen")
          .eq("id", user.id)
          .maybeSingle();

        const showcaseSeen = (profile as { showcase_seen?: boolean | null })?.showcase_seen === true;
        const url = request.nextUrl.clone();
        url.pathname = showcaseSeen ? "/dashboard" : "/welcome";
        url.search = "";
        return NextResponse.redirect(url);
      } catch {
        const url = request.nextUrl.clone();
        url.pathname = "/dashboard";
        url.search = "";
        return NextResponse.redirect(url);
      }
    }

    // NO ROUTE GUARD BLOCKS ACCESS TO THE REST OF THE APP.
    // A CA can skip the showcase and go straight to /dashboard or /clients immediately.
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

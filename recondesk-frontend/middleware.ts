import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

import {
  ONBOARDING_DONE_COOKIE,
  isOnboardingDoneForUser,
  onboardingDoneCookieOptions,
} from "@/lib/onboarding-cookie";

const API_ME = (base: string) =>
  `${base.replace(/\/+$/, "")}/api/v1/auth/me`;

/** Keep well under Vercel middleware limits; cold Railway must not hang the edge. */
const AUTH_ME_TIMEOUT_MS = 2500;

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

    const skipRedirect =
      pathname.startsWith("/onboarding") ||
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

    // Fast path: already confirmed onboarded for this user — no profile / API round-trip.
    if (isOnboardingDoneForUser(request.cookies.get(ONBOARDING_DONE_COOKIE)?.value, user.id)) {
      return redirectHomeToDashboard(request, response);
    }

    // Prefer Supabase (usually warm) over Railway `/auth/me` (cold starts cause 504s).
    try {
      const { data: profile, error: profileError } = await supabase
        .from("user_profiles")
        .select("onboarding_completed")
        .eq("id", user.id)
        .maybeSingle();

      if (!profileError && profile) {
        const done = (profile as { onboarding_completed?: boolean | null })
          .onboarding_completed === true;
        if (!done) {
          const url = request.nextUrl.clone();
          url.pathname = "/onboarding";
          url.search = "";
          return NextResponse.redirect(url);
        }
        response = withOnboardingCookie(response, user.id);
        return redirectHomeToDashboard(request, response);
      }
    } catch {
      // Fall through to timed Railway check.
    }

    const { data: sessionData } = await supabase.auth.getSession();
    const token = sessionData.session?.access_token;
    if (!token) {
      return response;
    }

    const apiBase =
      process.env.NEXT_PUBLIC_API_URL?.trim() || "http://localhost:8000";

    try {
      const meRes = await fetch(API_ME(apiBase), {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
        signal: AbortSignal.timeout(AUTH_ME_TIMEOUT_MS),
      });
      if (!meRes.ok) {
        return response;
      }
      const me = (await meRes.json()) as {
        onboarding_completed?: boolean | null;
      };
      const done = me.onboarding_completed === true;
      if (!done) {
        const url = request.nextUrl.clone();
        url.pathname = "/onboarding";
        url.search = "";
        return NextResponse.redirect(url);
      }

      response = withOnboardingCookie(response, user.id);
      return redirectHomeToDashboard(request, response);
    } catch {
      // Timeout / network: fail open so Vercel never returns MIDDLEWARE_INVOCATION_TIMEOUT.
      return response;
    }
  } catch {
    return passThrough(request);
  }
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};

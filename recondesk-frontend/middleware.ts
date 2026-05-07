import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

const API_ME = (base: string) =>
  `${base.replace(/\/+$/, "")}/api/v1/auth/me`;

/** Plain pass-through; use on errors so we never reuse a response that may be in a bad state. */
function passThrough(request: NextRequest) {
  return NextResponse.next({ request: { headers: request.headers } });
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

      if (pathname === "/" || pathname === "") {
        const url = request.nextUrl.clone();
        url.pathname = "/dashboard";
        url.search = "";
        return NextResponse.redirect(url);
      }
    } catch {
      return response;
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

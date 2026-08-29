import { createServerClient } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

/**
 * Allow only same-origin relative paths (blocks open redirects).
 */
function safeRedirectPath(raw: string | null): string {
  if (!raw) return "/dashboard";
  let path = raw;
  try {
    path = decodeURIComponent(raw);
  } catch {
    return "/";
  }
  if (!path.startsWith("/") || path.startsWith("//")) return "/";
  if (path.includes("://")) return "/";
  return path;
}

export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const redirectTo = safeRedirectPath(
    searchParams.get("redirectTo") ?? searchParams.get("next") ?? searchParams.get("redirect_to")
  );

  const errorDescription = searchParams.get("error_description");
  if (searchParams.get("error")) {
    const login = new URL("/login", origin);
    login.searchParams.set("error", errorDescription ?? searchParams.get("error") ?? "auth_error");
    return NextResponse.redirect(login);
  }

  if (!code) {
    const login = new URL("/login", origin);
    login.searchParams.set("error", "missing_code");
    return NextResponse.redirect(login);
  }

  let response = NextResponse.redirect(new URL(redirectTo, origin));

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => {
            response.cookies.set(name, value, options);
          });
        },
      },
    }
  );

  const { error } = await supabase.auth.exchangeCodeForSession(code);

  if (error) {
    const target = redirectTo.startsWith("/reset-password")
      ? new URL("/reset-password", origin)
      : new URL("/login", origin);
    target.searchParams.set("error_description", error.message);
    return NextResponse.redirect(target);
  }

  return response;
}

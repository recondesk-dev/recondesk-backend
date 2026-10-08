import { type NextRequest, NextResponse } from "next/server";

/**
 * Legacy auth callback route: redirect safely to dashboard or login.
 */
export async function GET(request: NextRequest) {
  const { origin, searchParams } = new URL(request.url);
  const redirectTo = searchParams.get("redirectTo") || "/dashboard";
  return NextResponse.redirect(new URL(redirectTo, origin));
}

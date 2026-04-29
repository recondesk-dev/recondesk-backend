import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * Returns the current user's Supabase access JWT using the server client
 * (reads HttpOnly / chunked cookies the browser Supabase client cannot see).
 * Same-origin only; used by client components to authorize FastAPI calls.
 */
export async function GET() {
  const supabase = createClient();
  const {
    data: { session },
    error,
  } = await supabase.auth.getSession();

  if (error || !session?.access_token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  return NextResponse.json({ access_token: session.access_token });
}

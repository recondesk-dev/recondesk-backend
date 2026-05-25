import { NextResponse } from "next/server";

export async function GET() {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    await fetch(`${apiUrl}/health`, { cache: "no-store" });
  } catch {
    // Ignore errors — the purpose is fire-and-forget.
  }
  return NextResponse.json({ ok: true });
}

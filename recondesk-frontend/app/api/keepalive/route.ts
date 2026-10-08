import { NextResponse } from "next/server";

export async function GET() {
  const apiUrl = (process.env.NEXT_PUBLIC_API_URL ?? "https://api.recondesk.in").replace(/\/+$/, "");
  let backendOk = false;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 3500);
  try {
    const res = await fetch(`${apiUrl}/health`, {
      cache: "no-store",
      signal: controller.signal,
    });
    backendOk = res.ok;
  } catch {
    backendOk = false;
  } finally {
    clearTimeout(timeoutId);
  }
  return NextResponse.json({ ok: true, backend: backendOk });
}

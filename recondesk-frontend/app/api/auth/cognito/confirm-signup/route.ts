import { NextRequest, NextResponse } from "next/server";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  ""
);

/**
 * Handles confirming signup with verification code.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email, confirmation_code } = body;

    if (!email || !confirmation_code) {
      return NextResponse.json(
        { error: "bad_request", message: "Email and confirmation code are required.", detail: "Email and confirmation code are required." },
        { status: 400 }
      );
    }

    const backendRes = await fetch(`${API_URL}/api/v1/auth/cognito/confirm-signup`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        email: email.trim(),
        confirmation_code: confirmation_code.trim(),
      }),
      cache: "no-store",
    });

    const data = await backendRes.json().catch(() => null);

    if (!backendRes.ok) {
      const detail = data?.detail || data?.message || "Confirmation failed";
      return NextResponse.json(
        {
          error: "confirmation_failed",
          detail,
          message: detail,
        },
        { status: backendRes.status }
      );
    }

    return NextResponse.json(data, { status: 200 });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Internal confirmation error";
    return NextResponse.json(
      { error: "server_error", message: msg, detail: msg },
      { status: 500 }
    );
  }
}

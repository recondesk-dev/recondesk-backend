import { NextRequest, NextResponse } from "next/server";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  ""
);

/**
 * Handles initiating forgot password flow with Cognito.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email } = body;

    if (!email) {
      return NextResponse.json(
        { error: "bad_request", message: "Email is required.", detail: "Email is required." },
        { status: 400 }
      );
    }

    const backendRes = await fetch(`${API_URL}/api/v1/auth/cognito/forgot-password`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ email: email.trim() }),
      cache: "no-store",
    });

    const data = await backendRes.json().catch(() => null);

    if (!backendRes.ok) {
      const detail = data?.detail || data?.message || "Password recovery request failed";
      return NextResponse.json(
        {
          error: "forgot_password_failed",
          detail,
          message: detail,
        },
        { status: backendRes.status }
      );
    }

    return NextResponse.json(data, { status: 200 });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Internal forgot password error";
    return NextResponse.json(
      { error: "server_error", message: msg, detail: msg },
      { status: 500 }
    );
  }
}

import { NextRequest, NextResponse } from "next/server";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  ""
);

/**
 * Handles confirming password reset with confirmation code and new password.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email, confirmation_code, new_password } = body;

    if (!email || !confirmation_code || !new_password) {
      return NextResponse.json(
        {
          error: "bad_request",
          message: "Email, confirmation code, and new password are required.",
          detail: "Email, confirmation code, and new password are required.",
        },
        { status: 400 }
      );
    }

    const backendRes = await fetch(`${API_URL}/api/v1/auth/cognito/confirm-forgot-password`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        email: email.trim(),
        confirmation_code: confirmation_code.trim(),
        new_password,
      }),
      cache: "no-store",
    });

    const data = await backendRes.json().catch(() => null);

    if (!backendRes.ok) {
      const detail = data?.detail || data?.message || "Password reset failed";
      return NextResponse.json(
        {
          error: "reset_password_failed",
          detail,
          message: detail,
        },
        { status: backendRes.status }
      );
    }

    return NextResponse.json(data, { status: 200 });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Internal reset password error";
    return NextResponse.json(
      { error: "server_error", message: msg, detail: msg },
      { status: 500 }
    );
  }
}

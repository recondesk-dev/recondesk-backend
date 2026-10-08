import { NextRequest, NextResponse } from "next/server";

const API_URL = (
  process.env.INTERNAL_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "https://api.recondesk.in"
).replace(/\/+$/, "");

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email, confirmation_code, new_password } = body;

    if (!email || !confirmation_code || !new_password) {
      return NextResponse.json(
        { error: "Email, confirmation code, and new password are required" },
        { status: 400 }
      );
    }

    const payload = JSON.stringify({
      email: email.trim().toLowerCase(),
      confirmation_code: confirmation_code.trim(),
      new_password,
    });
    const forwardHeaders = {
      "Content-Type": "application/json",
      "X-Forwarded-For": request.headers.get("x-forwarded-for") || request.ip || "",
    };

    let backendRes = await fetch(`${API_URL}/api/v1/auth/reset-password`, {
      method: "POST",
      headers: forwardHeaders,
      body: payload,
    });

    if (backendRes.status === 404) {
      backendRes = await fetch(`${API_URL}/auth/reset-password`, {
        method: "POST",
        headers: forwardHeaders,
        body: payload,
      });
    }

    if (backendRes.status === 404) {
      backendRes = await fetch(`${API_URL}/api/auth/reset-password`, {
        method: "POST",
        headers: forwardHeaders,
        body: payload,
      });
    }

    const data = await backendRes.json().catch(() => ({}));

    if (!backendRes.ok) {
      return NextResponse.json(
        { error: data.detail || "Invalid confirmation code or password requirements not met." },
        { status: backendRes.status }
      );
    }

    return NextResponse.json({
      success: true,
      message: data.message || "Password has been successfully reset.",
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Error resetting password";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

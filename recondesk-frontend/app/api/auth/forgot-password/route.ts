import { NextRequest, NextResponse } from "next/server";

const API_URL = (
  process.env.INTERNAL_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "https://api.recondesk.in"
).replace(/\/+$/, "");

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email } = body;

    if (!email) {
      return NextResponse.json(
        { error: "Email address is required" },
        { status: 400 }
      );
    }

    const payload = JSON.stringify({ email: email.trim().toLowerCase() });
    const forwardHeaders = {
      "Content-Type": "application/json",
      "X-Forwarded-For": request.headers.get("x-forwarded-for") || request.ip || "",
    };

    let backendRes = await fetch(`${API_URL}/api/v1/auth/forgot-password`, {
      method: "POST",
      headers: forwardHeaders,
      body: payload,
    });

    if (backendRes.status === 404) {
      backendRes = await fetch(`${API_URL}/auth/forgot-password`, {
        method: "POST",
        headers: forwardHeaders,
        body: payload,
      });
    }

    if (backendRes.status === 404) {
      backendRes = await fetch(`${API_URL}/api/auth/forgot-password`, {
        method: "POST",
        headers: forwardHeaders,
        body: payload,
      });
    }

    const data = await backendRes.json().catch(() => ({}));

    if (!backendRes.ok) {
      return NextResponse.json(
        { error: data.detail || "Unable to send reset code. Please try again." },
        { status: backendRes.status }
      );
    }

    return NextResponse.json({
      success: true,
      message: data.message || "Password reset code sent to email.",
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Error sending reset code";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

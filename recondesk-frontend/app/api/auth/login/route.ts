import { NextRequest, NextResponse } from "next/server";
import { setCognitoSessionCookies } from "@/lib/cognito/cookies";

const API_URL = (
  (process.env.NODE_ENV === "production"
    ? process.env.NEXT_PUBLIC_API_URL || process.env.INTERNAL_API_URL
    : process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL) ||
  "http://localhost:8000"
).replace(/\/+$/, "");

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email, password } = body;

    if (!email || !password) {
      return NextResponse.json(
        { error: "Email and password are required" },
        { status: 400 }
      );
    }

    const payload = JSON.stringify({ email: email.trim(), password });
    const forwardHeaders = {
      "Content-Type": "application/json",
      "X-Forwarded-For": request.headers.get("x-forwarded-for") || request.ip || "",
    };

    // Call backend /api/v1/auth/login with fallback to /auth/login
    let backendRes = await fetch(`${API_URL}/api/v1/auth/login`, {
      method: "POST",
      headers: forwardHeaders,
      body: payload,
    });

    if (backendRes.status === 404) {
      backendRes = await fetch(`${API_URL}/auth/login`, {
        method: "POST",
        headers: forwardHeaders,
        body: payload,
      });
    }

    const data = await backendRes.json();

    if (!backendRes.ok) {
      return NextResponse.json(
        { error: data.detail || "Invalid email or password" },
        { status: backendRes.status }
      );
    }

    const response = NextResponse.json({
      success: true,
      user: data.user,
      role: data.role,
    });

    // Set server-only Cognito session cookie
    if (data.access_token) {
      setCognitoSessionCookies(response, {
        accessToken: data.access_token,
        request,
      });
    }

    return response;
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Authentication error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

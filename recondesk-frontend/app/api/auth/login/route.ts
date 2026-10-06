import { NextRequest, NextResponse } from "next/server";
import { setCognitoSessionCookies } from "@/lib/cognito/cookies";

const API_URL = (
  process.env.INTERNAL_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
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

    // Call backend /auth/login (backed by AWS Cognito & Aurora)
    const backendRes = await fetch(`${API_URL}/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Forwarded-For": request.headers.get("x-forwarded-for") || request.ip || "",
      },
      body: JSON.stringify({ email: email.trim(), password }),
    });

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

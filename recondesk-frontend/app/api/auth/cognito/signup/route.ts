import { NextRequest, NextResponse } from "next/server";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  ""
);

/**
 * Handles Cognito signup by delegating to backend /api/v1/auth/cognito/signup.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email, password, full_name, firm_name, phone } = body;

    if (!email || !password) {
      return NextResponse.json(
        { error: "bad_request", message: "Email and password are required.", detail: "Email and password are required." },
        { status: 400 }
      );
    }

    const backendRes = await fetch(`${API_URL}/api/v1/auth/cognito/signup`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        email: email.trim(),
        password,
        full_name: full_name?.trim() || "",
        firm_name: firm_name?.trim() || "",
        phone: phone?.trim() || "",
      }),
      cache: "no-store",
    });

    const data = await backendRes.json().catch(() => null);

    if (!backendRes.ok) {
      const detail = data?.detail || data?.message || "Sign up failed";
      return NextResponse.json(
        {
          error: "signup_failed",
          detail,
          message: detail,
        },
        { status: backendRes.status }
      );
    }

    return NextResponse.json(data, { status: 200 });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Internal signup error";
    return NextResponse.json(
      { error: "server_error", message: msg, detail: msg },
      { status: 500 }
    );
  }
}

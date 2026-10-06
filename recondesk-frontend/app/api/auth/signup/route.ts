import { NextRequest, NextResponse } from "next/server";

const API_URL = (
  process.env.INTERNAL_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000"
).replace(/\/+$/, "");

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email, password, full_name, firm_name, phone } = body;

    if (!email || !password) {
      return NextResponse.json(
        { error: "Email and password are required" },
        { status: 400 }
      );
    }

    // Call backend /auth/signup (backed by AWS Cognito & Aurora)
    const backendRes = await fetch(`${API_URL}/auth/signup`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Forwarded-For": request.headers.get("x-forwarded-for") || request.ip || "",
      },
      body: JSON.stringify({
        email: email.trim(),
        password,
        full_name: full_name?.trim() || null,
        firm_name: firm_name?.trim() || null,
        phone: phone?.trim() || null,
      }),
    });

    const data = await backendRes.json();

    if (!backendRes.ok) {
      return NextResponse.json(
        { error: data.detail || "Unable to complete sign up" },
        { status: backendRes.status }
      );
    }

    return NextResponse.json(
      {
        success: true,
        user_id: data.user_id,
        message: data.message,
      },
      { status: 201 }
    );
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Registration error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

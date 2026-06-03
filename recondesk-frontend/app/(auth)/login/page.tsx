"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { EMAIL_VALIDATION_MESSAGE, isValidEmail } from "@/lib/auth-validation";
import { Eye, EyeOff, LogIn } from "lucide-react";
import React from "react";

const INPUT_ERROR_CLASS =
  "border-red-300 focus:border-red-400 focus:ring-red-500/20";

type LoginFieldErrors = {
  email?: string;
  password?: string;
};

function validateLoginForm(email: string, password: string): LoginFieldErrors {
  const errors: LoginFieldErrors = {};

  if (!email.trim() || !isValidEmail(email)) {
    errors.email = EMAIL_VALIDATION_MESSAGE;
  }
  if (!password) {
    errors.password = "Password is required";
  }

  return errors;
}

function RequiredLabel({
  htmlFor,
  children,
}: {
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <label htmlFor={htmlFor} className="mb-1 block text-sm font-medium text-gray-700">
      {children}
      <span className="text-red-600" aria-hidden="true">
        {" "}
        *
      </span>
    </label>
  );
}

export default function LoginPage() {
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<LoginFieldErrors>({});

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const validationErrors = validateLoginForm(email, password);
    if (Object.keys(validationErrors).length > 0) {
      setFieldErrors(validationErrors);
      return;
    }
    setFieldErrors({});

    setLoading(true);

    const supabase = createClient();
    const { error: authError } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    });

    if (authError) {
      setError("Incorrect email or password");
      setLoading(false);
    } else {
      router.push("/dashboard");
      router.refresh();
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="mb-10 text-center">
          <h1 className="font-brand inline-flex items-baseline justify-center gap-0 text-[64px] leading-none font-bold tracking-tight text-gray-900">
            <span>ReconDesk</span>
            <span className="text-[64px] leading-none text-purple-600" aria-hidden="true">
              •
            </span>
          </h1>
          <p className="mt-2 text-sm text-gray-500">Reconciliation made simple</p>
        </div>

        {/* Card */}
        <div className="rounded-2xl border border-gray-200 bg-white p-8 shadow-md">
          <h2 className="text-xl font-semibold text-gray-900 mb-1">Welcome back</h2>
          <p className="text-sm text-gray-500 mb-6">Sign in to your account</p>

          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              {error}
            </div>
          )}

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <RequiredLabel htmlFor="email">Email address</RequiredLabel>
              <input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (fieldErrors.email) {
                    setFieldErrors((prev) => {
                      const next = { ...prev };
                      delete next.email;
                      return next;
                    });
                  }
                }}
                className={`input-field${fieldErrors.email ? ` ${INPUT_ERROR_CLASS}` : ""}`}
                aria-invalid={fieldErrors.email ? true : undefined}
              />
              {fieldErrors.email && (
                <p className="mt-1 text-xs text-red-600">{fieldErrors.email}</p>
              )}
            </div>

            <div>
              <div className="mb-1 flex items-center justify-between">
                <label htmlFor="password" className="block text-sm font-medium text-gray-700">
                  Password
                  <span className="text-red-600" aria-hidden="true">
                    {" "}
                    *
                  </span>
                </label>
                <Link
                  href="/forgot-password"
                  className="text-xs text-purple-600 hover:text-purple-700 font-medium"
                >
                  Forgot password?
                </Link>
              </div>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    if (fieldErrors.password) {
                      setFieldErrors((prev) => {
                        const next = { ...prev };
                        delete next.password;
                        return next;
                      });
                    }
                  }}
                  className={`input-field pr-11${fieldErrors.password ? ` ${INPUT_ERROR_CLASS}` : ""}`}
                  aria-invalid={fieldErrors.password ? true : undefined}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {fieldErrors.password && (
                <p className="mt-1 text-xs text-red-600">{fieldErrors.password}</p>
              )}
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full flex items-center justify-center gap-2 mt-2"
            >
              {loading ? (
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <LogIn size={16} />
              )}
              {loading ? "Signing in..." : "Sign in"}
            </button>
          </form>
        </div>

        <p className="text-center text-sm text-gray-500 mt-6">
          Don&apos;t have an account?{" "}
          <Link href="/signup" className="text-purple-600 hover:text-purple-700 font-medium">
            Create account
          </Link>
        </p>
      </div>
    </div>
  );
}

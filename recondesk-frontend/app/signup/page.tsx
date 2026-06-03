"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import {
  getPasswordStrengthLabel,
  getPasswordStrengthScore,
  getUnmetPasswordRules,
  isValidPassword,
} from "@/lib/auth-validation";
import { Eye, EyeOff, UserPlus } from "lucide-react";

const DEFAULT_API_URL = "http://localhost:8000";

function SignupForm() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [form, setForm] = useState({
    name: "",
    firmName: "",
    phone: "",
    email: "",
    password: "",
  });
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inviteRoleRaw =
    searchParams.get("invite_role")?.trim().toLowerCase() ?? "";
  const inviteToken = searchParams.get("invite_token")?.trim() ?? "";

  useEffect(() => {
    const email = searchParams.get("email")?.trim();
    if (email) {
      setForm((prev) => ({ ...prev, email }));
    }
  }, [searchParams]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  };

  const passwordStrengthScore = getPasswordStrengthScore(form.password);
  const passwordStrengthLabel = getPasswordStrengthLabel(passwordStrengthScore);
  const unmetPasswordRules = getUnmetPasswordRules(form.password);
  const showPasswordFeedback = form.password.length > 0;

  const strengthBarColor =
    passwordStrengthScore <= 1
      ? "bg-red-500"
      : passwordStrengthScore <= 3
        ? "bg-amber-500"
        : "bg-green-500";

  const strengthTextColor =
    passwordStrengthScore <= 1
      ? "text-red-600"
      : passwordStrengthScore <= 3
        ? "text-amber-600"
        : "text-green-600";

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!isValidPassword(form.password)) return;

    setLoading(true);

    const supabase = createClient();

    const metadataRole =
      inviteRoleRaw === "staff"
        ? "Staff"
        : inviteRoleRaw === "admin"
          ? "Admin"
          : "Admin";

    const siteUrl = (
      process.env.NEXT_PUBLIC_SITE_URL ?? window.location.origin
    ).replace(/\/$/, "");
    const { error } = await supabase.auth.signUp({
      email: form.email,
      password: form.password,
      options: {
        emailRedirectTo: `${siteUrl}/auth/callback`,
        data: {
          full_name: form.name,
          firm_name: form.firmName,
          phone: form.phone,
          role: metadataRole,
        },
      },
    });

    if (error) {
      setError(error.message);
      setLoading(false);
      return;
    }

    if (inviteToken) {
      const apiUrl = (
        process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_URL
      ).replace(/\/$/, "");
      try {
        await fetch(
          `${apiUrl}/api/team/accept/${encodeURIComponent(inviteToken)}`,
          {
            method: "POST",
            headers: { Accept: "application/json" },
          },
        );
      } catch {
        /* Invitation can be completed via /team/accept/{token} if this fails */
      }
    }

    setLoading(false);
    router.replace("/dashboard");
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-10 text-center">
          <h1 className="font-brand inline-flex items-baseline justify-center gap-0 text-[64px] leading-none font-bold tracking-tight text-gray-900">
            <span>ReconDesk</span>
            <span className="text-[64px] leading-none text-purple-600" aria-hidden="true">
              •
            </span>
          </h1>
          <p className="mt-2 text-sm text-gray-500">Reconciliation made simple</p>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-8 shadow-md">
          <h2 className="mb-1 text-xl font-semibold text-gray-900">Create your account</h2>
          <p className="mb-6 text-sm text-gray-500">Get started with ReconDesk for free</p>

          {inviteRoleRaw ? (
            <div className="mb-4 rounded-lg border border-purple-100 bg-purple-50 px-3 py-2 text-sm text-purple-950">
              You&apos;re signing up from a team invitation
              {inviteRoleRaw === "admin" || inviteRoleRaw === "staff"
                ? ` (${inviteRoleRaw})`
                : ""}
              .
            </div>
          ) : null}

          {error && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <form onSubmit={handleSignup} className="space-y-5">
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 sm:gap-4">
              <div>
                <label htmlFor="name" className="mb-1 block text-sm font-medium text-gray-700">
                  Full name
                </label>
                <input
                  id="name"
                  name="name"
                  type="text"
                  required
                  value={form.name}
                  onChange={handleChange}
                  className="input-field"
                />
              </div>
              <div>
                <label htmlFor="phone" className="mb-1 block text-sm font-medium text-gray-700">
                  Phone number
                </label>
                <input
                  id="phone"
                  name="phone"
                  type="tel"
                  value={form.phone}
                  onChange={handleChange}
                  placeholder="+91 98765 43210"
                  className="input-field"
                />
              </div>
            </div>

            <div>
              <label htmlFor="firmName" className="mb-1 block text-sm font-medium text-gray-700">
                Firm / Company name (If any)
              </label>
              <input
                id="firmName"
                name="firmName"
                type="text"
                value={form.firmName}
                onChange={handleChange}
                className="input-field"
              />
            </div>

            <div>
              <label htmlFor="email" className="mb-1 block text-sm font-medium text-gray-700">
                Work email
              </label>
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                required
                value={form.email}
                onChange={handleChange}
                className="input-field"
              />
            </div>

            <div>
              <label htmlFor="password" className="mb-1 block text-sm font-medium text-gray-700">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  required
                  value={form.password}
                  onChange={handleChange}
                  placeholder="Create a password"
                  className={`input-field pr-11${unmetPasswordRules.length > 0 && showPasswordFeedback ? " border-red-300 focus:border-red-400 focus:ring-red-500/20" : ""}`}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              {showPasswordFeedback && (
                <div className="mt-2 space-y-2">
                  <div className="flex items-center gap-2">
                    <div className="flex h-1 flex-1 gap-0.5 overflow-hidden rounded-full bg-gray-100">
                      {Array.from({ length: 5 }).map((_, i) => (
                        <div
                          key={i}
                          className={`h-full flex-1 rounded-full transition-colors ${
                            i < passwordStrengthScore ? strengthBarColor : "bg-gray-200"
                          }`}
                        />
                      ))}
                    </div>
                    <span className={`text-xs font-medium ${strengthTextColor}`}>
                      {passwordStrengthLabel}
                    </span>
                  </div>
                  {unmetPasswordRules.length > 0 && (
                    <ul className="space-y-0.5 text-xs text-red-600">
                      {unmetPasswordRules.map((rule) => (
                        <li key={rule.id}>{rule.label}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>

            <button
              type="submit"
              disabled={loading || !isValidPassword(form.password)}
              className="btn-primary mt-1"
            >
              {loading ? (
                <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <UserPlus size={16} />
              )}
              {loading ? "Creating account..." : "Create account"}
            </button>

            <p className="text-center text-xs text-gray-400">
              By signing up, you agree to our{" "}
              <Link href="/terms" className="text-purple-600 hover:underline">Terms</Link>{" "}
              and{" "}
              <Link href="/privacy" className="text-purple-600 hover:underline">Privacy Policy</Link>.
            </p>
          </form>
        </div>

        <p className="mt-6 text-center text-sm text-gray-500">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-purple-600 hover:text-purple-700">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}

export default function SignupPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
          <div className="h-10 w-10 animate-spin rounded-full border-4 border-purple-600 border-t-transparent" />
        </div>
      }
    >
      <SignupForm />
    </Suspense>
  );
}

"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import {
  clearCachedAuthRole,
  invalidateAuthProfileCache,
} from "@/lib/auth-profile";
import {
  EMAIL_VALIDATION_MESSAGE,
  getPasswordStrengthLabel,
  getPasswordStrengthScore,
  getUnmetPasswordRules,
  isValidEmail,
  isValidPassword,
} from "@/lib/auth-validation";
import { Eye, EyeOff, UserPlus } from "lucide-react";

const DEFAULT_API_URL = "http://localhost:8000";

type SignupFieldErrors = {
  name?: string;
  phone?: string;
  firmName?: string;
  email?: string;
  password?: string;
};

const INPUT_ERROR_CLASS =
  "border-red-300 focus:border-red-400 focus:ring-red-500/20";

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

function validateSignupForm(form: {
  name: string;
  firmName: string;
  phone: string;
  email: string;
  password: string;
}): SignupFieldErrors {
  const errors: SignupFieldErrors = {};

  if (!form.name.trim()) {
    errors.name = "Name is required";
  }
  if (!/^\d{10}$/.test(form.phone)) {
    errors.phone = "Enter a valid 10-digit mobile number";
  }
  if (!form.firmName.trim()) {
    errors.firmName = "Firm or company name is required";
  }
  if (!isValidEmail(form.email)) {
    errors.email = EMAIL_VALIDATION_MESSAGE;
  }
  if (!form.password.trim()) {
    errors.password = "Password is required";
  } else if (!isValidPassword(form.password)) {
    errors.password = "Password is required";
  }

  return errors;
}

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
  const [fieldErrors, setFieldErrors] = useState<SignupFieldErrors>({});

  const inviteRoleRaw =
    searchParams.get("invite_role")?.trim().toLowerCase() ?? "";
  const inviteToken = searchParams.get("invite_token")?.trim() ?? "";

  useEffect(() => {
    const email = searchParams.get("email")?.trim();
    if (email) {
      setForm((prev) => ({ ...prev, email }));
    }
  }, [searchParams]);

  const clearFieldError = (name: keyof SignupFieldErrors) => {
    setFieldErrors((prev) => {
      if (!prev[name]) return prev;
      const next = { ...prev };
      delete next[name];
      return next;
    });
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setForm((prev) => ({ ...prev, [name]: value }));
    clearFieldError(name as keyof SignupFieldErrors);
  };

  const handlePhoneChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const digits = e.target.value.replace(/\D/g, "").slice(0, 10);
    setForm((prev) => ({ ...prev, phone: digits }));
    clearFieldError("phone");
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

    const validationErrors = validateSignupForm(form);
    if (Object.keys(validationErrors).length > 0) {
      setFieldErrors(validationErrors);
      return;
    }
    setFieldErrors({});

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

    clearCachedAuthRole();
    await invalidateAuthProfileCache();

    setLoading(false);
    router.replace("/dashboard");
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-10 text-center">
          <h1 className="font-brand inline-flex items-baseline justify-center gap-0 text-[64px] leading-none font-bold tracking-tight text-gray-900">
            <span>ReconDesk</span>
            <span className="text-[64px] leading-none text-brand" aria-hidden="true">
              •
            </span>
          </h1>
          <p className="mt-2 text-sm text-gray-900">Protect your clients&apos; ITC. Every month.</p>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-8 shadow-md">
          <h2 className="mb-1 text-xl font-semibold text-gray-900">Create your account</h2>
          <p className="mb-6 text-sm text-gray-500">Get started with ReconDesk for free</p>

          {inviteRoleRaw ? (
            <div className="mb-4 rounded-lg border border-brand-dim bg-brand-dim px-3 py-2 text-sm text-[#111827]">
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
                <RequiredLabel htmlFor="name">Name</RequiredLabel>
                <input
                  id="name"
                  name="name"
                  type="text"
                  value={form.name}
                  onChange={handleChange}
                  className={`input-field${fieldErrors.name ? ` ${INPUT_ERROR_CLASS}` : ""}`}
                  aria-invalid={fieldErrors.name ? true : undefined}
                />
                {fieldErrors.name && (
                  <p className="mt-1 text-xs text-red-600">{fieldErrors.name}</p>
                )}
              </div>
              <div>
                <RequiredLabel htmlFor="phone">Phone number</RequiredLabel>
                <input
                  id="phone"
                  name="phone"
                  type="text"
                  inputMode="numeric"
                  autoComplete="tel"
                  maxLength={10}
                  value={form.phone}
                  onChange={handlePhoneChange}
                  className={`input-field${fieldErrors.phone ? ` ${INPUT_ERROR_CLASS}` : ""}`}
                  aria-invalid={fieldErrors.phone ? true : undefined}
                />
                {fieldErrors.phone && (
                  <p className="mt-1 text-xs text-red-600">{fieldErrors.phone}</p>
                )}
              </div>
            </div>

            <div>
              <RequiredLabel htmlFor="firmName">Firm / Company name</RequiredLabel>
              <input
                id="firmName"
                name="firmName"
                type="text"
                value={form.firmName}
                onChange={handleChange}
                className={`input-field${fieldErrors.firmName ? ` ${INPUT_ERROR_CLASS}` : ""}`}
                aria-invalid={fieldErrors.firmName ? true : undefined}
              />
              {fieldErrors.firmName && (
                <p className="mt-1 text-xs text-red-600">{fieldErrors.firmName}</p>
              )}
            </div>

            <div>
              <RequiredLabel htmlFor="email">Work email</RequiredLabel>
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                value={form.email}
                onChange={handleChange}
                className={`input-field${fieldErrors.email ? ` ${INPUT_ERROR_CLASS}` : ""}`}
                aria-invalid={fieldErrors.email ? true : undefined}
              />
              {fieldErrors.email && (
                <p className="mt-1 text-xs text-red-600">{fieldErrors.email}</p>
              )}
            </div>

            <div>
              <RequiredLabel htmlFor="password">Password</RequiredLabel>
              <div className="relative">
                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  value={form.password}
                  onChange={handleChange}
                  placeholder="Create a password"
                  className={`input-field pr-11${
                    fieldErrors.password ||
                    (unmetPasswordRules.length > 0 && showPasswordFeedback)
                      ? ` ${INPUT_ERROR_CLASS}`
                      : ""
                  }`}
                  aria-invalid={fieldErrors.password ? true : undefined}
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
              {fieldErrors.password && (
                <p className="mt-1 text-xs text-red-600">{fieldErrors.password}</p>
              )}
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
              disabled={loading}
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
              <Link href="/terms" className="text-brand hover:underline">Terms</Link>{" "}
              and{" "}
              <Link href="/privacy" className="text-brand hover:underline">Privacy Policy</Link>.
            </p>
          </form>
        </div>

        <p className="mt-6 text-center text-sm text-gray-500">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-brand hover:text-brand-hover">
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
          <div className="h-10 w-10 animate-spin rounded-full border-4 border-brand border-t-transparent" />
        </div>
      }
    >
      <SignupForm />
    </Suspense>
  );
}

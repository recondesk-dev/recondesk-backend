"use client";

import { useState } from "react";
import Link from "next/link";
import { Logo } from "@/components/ui/Logo";
import { Mail } from "lucide-react";

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const trimmed = email.trim();
    if (!trimmed || !EMAIL_REGEX.test(trimmed)) {
      setError("Please enter a valid email address.");
      return;
    }

    setLoading(true);

    try {
      const res = await fetch("/api/auth/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: trimmed }),
      });
      const data = await res.json().catch(() => ({}));
      setLoading(false);

      if (!res.ok) {
        setError(data.error || data.detail || "Unable to send reset code. Please try again.");
        return;
      }

      setSuccess(true);
    } catch {
      setLoading(false);
      setError("An unexpected error occurred. Please try again.");
    }
  };

  return (
    <div className="recondesk-textured-bg min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="mb-10 text-center flex flex-col items-center">
          <Logo width={280} height={50} className="mb-2" />
          <p className="mt-2 text-sm text-gray-900">Protect your clients&apos; ITC. Every month.</p>
        </div>

        <div className="bg-white rounded-[22px] shadow-[var(--shadow-lift)] border border-white/85 p-8">
          <h2 className="text-xl font-semibold text-gray-900 mb-1">Reset your password</h2>
          <p className="text-sm text-gray-500 mb-6">
            Enter your email and we&apos;ll send you a password reset confirmation code
          </p>

          {success ? (
            <div className="space-y-4">
              <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-lg text-sm text-emerald-800">
                <p className="font-semibold mb-1">Reset code sent!</p>
                <p className="text-emerald-700">
                  We&apos;ve sent a password reset confirmation code to <strong>{email}</strong>. Please check your inbox (and spam folder).
                </p>
              </div>
              <Link
                href={`/reset-password?email=${encodeURIComponent(email.trim())}`}
                className="btn-primary w-full flex items-center justify-center gap-2"
              >
                Enter Confirmation Code &rarr;
              </Link>
            </div>
          ) : (
            <>
              {error && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                  {error}
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1.5">
                    Email address
                  </label>
                  <input
                    id="email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="input-field"
                  />
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="btn-primary w-full flex items-center justify-center gap-2 mt-2"
                >
                  {loading ? (
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                      <circle
                        className="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                      />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                      />
                    </svg>
                  ) : (
                    <Mail size={16} />
                  )}
                  {loading ? "Sending..." : "Send Reset Code"}
                </button>
              </form>
            </>
          )}
        </div>

        <p className="text-center text-sm text-gray-500 mt-6">
          <Link href="/login" className="text-brand hover:text-brand-hover font-medium">
            Back to login
          </Link>
        </p>
      </div>
    </div>
  );
}

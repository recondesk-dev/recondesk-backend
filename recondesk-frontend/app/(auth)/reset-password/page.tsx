"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Logo } from "@/components/ui/Logo";
import { Eye, EyeOff, KeyRound } from "lucide-react";

export default function ResetPasswordPage() {
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [confirmationCode, setConfirmationCode] = useState("");
  const [resetSuccess, setResetSuccess] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const searchParams = new URLSearchParams(window.location.search);
    const queryEmail = searchParams.get("email");
    if (queryEmail) setEmail(queryEmail);
    const queryCode = searchParams.get("code") || searchParams.get("confirmation_code");
    if (queryCode && !queryCode.includes("-") && queryCode.length <= 10) {
      setConfirmationCode(queryCode);
    }

    const errorDesc =
      searchParams.get("error_description") ||
      searchParams.get("error");
    if (errorDesc) {
      setError(decodeURIComponent(errorDesc.replace(/\+/g, " ")));
    }
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (newPassword.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }

    if (newPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    if (!email.trim()) {
      setError("Please enter your email address.");
      return;
    }
    if (!confirmationCode.trim()) {
      setError("Please enter the verification code sent to your email.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/auth/cognito/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim(),
          confirmation_code: confirmationCode.trim(),
          new_password: newPassword,
        }),
      });
      const data = await res.json().catch(() => null);
      setLoading(false);

      if (!res.ok) {
        setError(data?.detail || data?.message || "Failed to reset password.");
        return;
      }

      setResetSuccess(true);
      setTimeout(() => {
        router.push("/login?password_reset=true");
      }, 1500);
    } catch {
      setError("Failed to reset password. Please try again.");
      setLoading(false);
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
          <h2 className="text-xl font-semibold text-gray-900 mb-1">Set a new password</h2>
          <p className="text-sm text-gray-500 mb-6">Choose a strong password for your account</p>

          {resetSuccess ? (
            <div className="p-4 bg-green-50 border border-green-200 rounded-lg text-sm text-green-800">
              Password has been reset successfully. Redirecting to sign in...
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
                  <label
                    htmlFor="email"
                    className="block text-sm font-medium text-gray-700 mb-1.5"
                  >
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

                <div>
                  <label
                    htmlFor="confirmation-code"
                    className="block text-sm font-medium text-gray-700 mb-1.5"
                  >
                    Verification code
                  </label>
                  <input
                    id="confirmation-code"
                    type="text"
                    autoComplete="one-time-code"
                    required
                    value={confirmationCode}
                    onChange={(e) => setConfirmationCode(e.target.value)}
                    placeholder="6-digit verification code"
                    className="input-field font-mono text-center tracking-widest"
                  />
                </div>

                <div>
                  <label
                    htmlFor="new-password"
                    className="block text-sm font-medium text-gray-700 mb-1.5"
                  >
                    New Password
                  </label>
                  <div className="relative">
                    <input
                      id="new-password"
                      type={showNewPassword ? "text" : "password"}
                      autoComplete="new-password"
                      required
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      placeholder="••••••••"
                      className="input-field pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowNewPassword(!showNewPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                    >
                      {showNewPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>

                <div>
                  <label
                    htmlFor="confirm-password"
                    className="block text-sm font-medium text-gray-700 mb-1.5"
                  >
                    Confirm Password
                  </label>
                  <div className="relative">
                    <input
                      id="confirm-password"
                      type={showConfirmPassword ? "text" : "password"}
                      autoComplete="new-password"
                      required
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      placeholder="••••••••"
                      className="input-field pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                    >
                      {showConfirmPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full btn-primary flex items-center justify-center gap-2 py-2.5 mt-2"
                >
                  <KeyRound size={16} />
                  {loading ? "Resetting password..." : "Reset password"}
                </button>
              </form>
            </>
          )}

          <div className="mt-6 text-center">
            <Link
              href="/login"
              className="text-sm font-medium text-brand hover:underline"
            >
              Back to sign in
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

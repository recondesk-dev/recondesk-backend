"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useToast } from "@/components/providers/ToastProvider";
import type { AcceptInviteResponse } from "@/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function AcceptInvitePage({
  params,
}: {
  params: { token: string };
}) {
  const router = useRouter();
  const toast = useToast();
  const rawToken = decodeURIComponent(params.token ?? "");

  const [phase, setPhase] = useState<"loading" | "error" | "done">("loading");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      if (!rawToken.trim()) {
        setErrorMsg("Invalid invitation link.");
        setPhase("error");
        return;
      }

      try {
        const res = await fetch(`${API_URL}/api/team/accept/${encodeURIComponent(rawToken.trim())}`, {
          method: "POST",
          headers: { Accept: "application/json" },
        });
        let body: unknown = null;
        try {
          body = await res.json();
        } catch {
          body = null;
        }

        if (cancelled) return;

        if (!res.ok) {
          const detail =
            typeof body === "object" &&
            body !== null &&
            "detail" in body &&
            typeof (body as { detail: unknown }).detail === "string"
              ? (body as { detail: string }).detail
              : "This invitation is invalid or has expired.";
          setErrorMsg(detail);
          setPhase("error");
          toast(detail, "error");
          return;
        }

        const parsed = body as AcceptInviteResponse;

        if (parsed.status === "accepted") {
          setPhase("done");
          toast("Welcome — joining your firm workspace.", "success");
          window.setTimeout(() => {
            router.replace(parsed.redirect === "/dashboard" ? "/" : parsed.redirect || "/");
          }, 900);
          return;
        }

        if (parsed.status === "signup_required") {
          const q = new URLSearchParams({
            email: parsed.email ?? "",
            invite_role: parsed.role ?? "staff",
          });
          router.replace(`/signup?${q.toString()}`);
          return;
        }

        setErrorMsg("Unexpected response from server.");
        setPhase("error");
      } catch {
        if (!cancelled) {
          const msg = "Something went wrong. Please try again.";
          setErrorMsg(msg);
          setPhase("error");
          toast(msg, "error");
        }
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, [rawToken, router]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-[var(--bg)] px-4 py-12">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-8 py-10 text-center shadow-sm">
        {phase === "loading" && (
          <>
            <div
              className="mx-auto mb-6 h-12 w-12 animate-spin rounded-full border-4 border-[var(--accent)] border-t-transparent"
              aria-hidden
            />
            <h1 className="text-lg font-semibold text-[var(--text-primary)]">
              Accepting invitation…
            </h1>
            <p className="mt-2 text-sm text-[var(--text-secondary)]">
              Please wait while we verify your invite link.
            </p>
          </>
        )}

        {phase === "error" && errorMsg && (
          <>
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-red-100 text-xl font-bold text-red-700">
              !
            </div>
            <h1 className="text-lg font-semibold text-[var(--text-primary)]">
              Invitation unavailable
            </h1>
            <p className="mt-2 text-sm text-[var(--text-secondary)]">{errorMsg}</p>
            <button
              type="button"
              className="mt-8 inline-flex min-h-[44px] w-full items-center justify-center rounded-lg bg-[var(--accent)] px-4 text-sm font-semibold text-white"
              onClick={() => router.replace("/login")}
            >
              Back to sign in
            </button>
          </>
        )}

        {phase === "done" && (
          <>
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
              ✓
            </div>
            <h1 className="text-lg font-semibold text-[var(--text-primary)]">
              You&apos;re in
            </h1>
            <p className="mt-2 text-sm text-[var(--text-secondary)]">
              Redirecting to your dashboard…
            </p>
          </>
        )}
      </div>
    </div>
  );
}

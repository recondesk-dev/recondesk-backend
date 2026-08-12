"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function OnboardingPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/dashboard");
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#F7F7F8]">
      <div className="text-center">
        <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-[var(--ink)] border-t-transparent" />
        <p className="mt-4 text-sm font-medium text-gray-500">Redirecting to dashboard…</p>
      </div>
    </div>
  );
}

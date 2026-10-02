"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

/**
 * Listens for recovery links on root path and routes to /reset-password.
 * Supabase auth listeners removed (100% Cognito Cutover).
 */
export function AuthRecoveryListener() {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (typeof window !== "undefined" && pathname === "/") {
      const hash = window.location.hash;
      if (hash && (hash.includes("type=recovery") || hash.includes("access_token"))) {
        router.push(`/reset-password${hash}`);
      }
    }
  }, [router, pathname]);

  return null;
}

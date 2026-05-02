"use client";

import { useEffect, useState } from "react";
import { subscribeAccessToken } from "@/lib/supabase/client";

/**
 * Resolves to `null` until the first subscription callback, then the JWT string or `false`.
 */
export function useAccessToken(): string | false | null {
  const [token, setToken] = useState<string | false | null>(null);

  useEffect(() => subscribeAccessToken(setToken), []);

  return token;
}

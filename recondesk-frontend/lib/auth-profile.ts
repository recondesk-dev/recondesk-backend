import { mutate } from "swr";

import { authApi, type AuthMeProfile } from "@/lib/api";

/** SWR options for `/auth/me` — always revalidate; never serve a stale cached role. */
export const AUTH_PROFILE_SWR_OPTIONS = {
  revalidateOnMount: true,
  revalidateOnFocus: true,
  revalidateOnReconnect: true,
  dedupingInterval: 0,
  keepPreviousData: false,
} as const;

const CACHED_ROLE_KEYS = [
  "user_role",
  "auth_role",
  "recondesk_role",
  "recondesk_user_role",
] as const;

export function normalizeAuthRole(raw: string | null | undefined): "admin" | "staff" {
  const role = (raw ?? "").trim().toLowerCase();
  if (role === "staff") return "staff";
  return "admin";
}

export function clearCachedAuthRole(): void {
  if (typeof window === "undefined") return;
  for (const key of CACHED_ROLE_KEYS) {
    try {
      localStorage.removeItem(key);
      sessionStorage.removeItem(key);
    } catch {
      /* private mode / blocked storage */
    }
  }
}

export function isAuthProfileSwrKey(key: unknown): boolean {
  if (!Array.isArray(key)) return false;
  const tag = String(key[0] ?? "");
  const second = String(key[1] ?? "");
  if (tag === "/api/v1/auth/me") return true;
  if (second === "me" || second === "/api/v1/auth/me") return true;
  if (
    tag === "onb-me" ||
    tag === "clients-me" ||
    tag === "settings-me" ||
    tag.endsWith("-me")
  ) {
    return true;
  }
  if (tag === "dw" && (second === "me" || second === "me-detail")) return true;
  return false;
}

export async function invalidateAuthProfileCache(): Promise<void> {
  await mutate(
    (key) => isAuthProfileSwrKey(key),
    undefined,
    { revalidate: true }
  );
}

/** Fetch profile + role fresh from user_profiles (via backend), never from JWT. */
export async function fetchFreshAuthProfile(token: string): Promise<AuthMeProfile> {
  const profile = await authApi.me(token, { fresh: true });
  return {
    ...profile,
    role: normalizeAuthRole(profile.role),
  };
}

export function authProfileFetcher(token: string): Promise<AuthMeProfile> {
  return fetchFreshAuthProfile(token);
}

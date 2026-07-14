/** Cookie set once onboarding is confirmed — middleware skips cold Railway `/auth/me`. */
export const ONBOARDING_DONE_COOKIE = "rd_ob";

/** 30 days — soft UX gate, not a security boundary. */
export const ONBOARDING_DONE_MAX_AGE_SEC = 60 * 60 * 24 * 30;

export function isOnboardingDoneForUser(
  cookieValue: string | undefined,
  userId: string
): boolean {
  if (!cookieValue || !userId) return false;
  try {
    return decodeURIComponent(cookieValue) === userId;
  } catch {
    return cookieValue === userId;
  }
}

export function onboardingDoneCookieOptions() {
  return {
    path: "/",
    maxAge: ONBOARDING_DONE_MAX_AGE_SEC,
    sameSite: "lax" as const,
    httpOnly: false,
    secure: process.env.NODE_ENV === "production",
  };
}

/** Client-side: mark onboarding done so the next navigation skips `/auth/me`. */
export function setOnboardingDoneCookie(userId: string): void {
  if (typeof document === "undefined" || !userId) return;
  const secure =
    typeof window !== "undefined" && window.location.protocol === "https:"
      ? "; Secure"
      : "";
  document.cookie = `${ONBOARDING_DONE_COOKIE}=${encodeURIComponent(userId)}; Path=/; Max-Age=${ONBOARDING_DONE_MAX_AGE_SEC}; SameSite=Lax${secure}`;
}

export function clearOnboardingDoneCookie(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${ONBOARDING_DONE_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
}

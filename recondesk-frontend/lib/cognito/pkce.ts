import crypto from "crypto";

/**
 * Generate a cryptographically random high-entropy string for PKCE code_verifier.
 * RFC 7636 specifies a string between 43 and 128 characters using unreserved characters.
 */
export function generateCodeVerifier(length: number = 64): string {
  const byteLength = Math.max(32, Math.min(96, length));
  return crypto.randomBytes(byteLength).toString("base64url").slice(0, length);
}

/**
 * Generate the PKCE code_challenge from a code_verifier using S256 (SHA-256 base64url).
 * code_challenge = BASE64URL(SHA256(code_verifier))
 */
export function generateCodeChallenge(verifier: string): string {
  return crypto.createHash("sha256").update(verifier).digest("base64url");
}

/**
 * Generate a cryptographically random state parameter to prevent CSRF attacks.
 */
export function generateOAuthState(length: number = 32): string {
  return crypto.randomBytes(length).toString("hex");
}

/**
 * Generate a cryptographically random nonce parameter to prevent replay attacks.
 */
export function generateOAuthNonce(length: number = 32): string {
  return crypto.randomBytes(length).toString("hex");
}

/**
 * Validate that the returned OAuth state matches the expected state.
 * Uses timing-safe equality comparison where possible.
 */
export function validateOAuthState(
  returnedState: string | null | undefined,
  expectedState: string | null | undefined
): boolean {
  if (!returnedState || !expectedState) return false;
  if (returnedState.length !== expectedState.length) return false;
  try {
    return crypto.timingSafeEqual(
      Buffer.from(returnedState, "utf-8"),
      Buffer.from(expectedState, "utf-8")
    );
  } catch {
    return false;
  }
}

/**
 * Approved application-relative root path prefixes.
 * Only redirects matching these prefixes will be accepted.
 */
const APPROVED_PATH_PREFIXES = [
  "/dashboard",
  "/welcome",
  "/clients",
  "/reconcile",
  "/team",
  "/billing",
  "/notices",
  "/settings",
] as const;

/**
 * Sanitizes and validates a post-login redirect path.
 *
 * Strict Security Rules:
 *   1. Must not be empty or non-string.
 *   2. Must start with exactly one '/' and not be followed by '/' or '\\'.
 *   3. Rejects protocol-relative URLs (e.g. //evil.com).
 *   4. Rejects backslash evasion tricks (e.g. /\\evil.com, \\evil.com).
 *   5. Rejects absolute schemes (e.g. https://, http://, javascript:, data:).
 *   6. Rejects newlines and control characters.
 *   7. Must match an approved application path prefix.
 *
 * Falls back to '/dashboard' if any validation fails.
 */
export function sanitizeRedirectPath(
  path: string | null | undefined,
  fallback: string = "/dashboard"
): string {
  if (!path || typeof path !== "string") {
    return fallback;
  }

  const trimmed = path.trim();
  if (!trimmed) {
    return fallback;
  }

  // Reject newlines and control characters
  if (/[\r\n\t\0]/.test(trimmed)) {
    return fallback;
  }

  // Reject protocol-relative or backslash-prefixed paths (//evil.com, /\evil.com, \evil.com)
  if (
    !trimmed.startsWith("/") ||
    trimmed.startsWith("//") ||
    trimmed.startsWith("/\\") ||
    trimmed.startsWith("\\")
  ) {
    return fallback;
  }

  // Reject any backslash anywhere in path to prevent Windows / browser normalization exploits
  if (trimmed.includes("\\")) {
    return fallback;
  }

  // Attempt URL parsing with dummy localhost origin to verify origin stability
  try {
    const dummyOrigin = "http://localhost";
    const parsed = new URL(trimmed, dummyOrigin);

    // If parsing changed the origin or protocol, reject immediately
    if (parsed.origin !== dummyOrigin || parsed.protocol !== "http:") {
      return fallback;
    }

    const pathname = parsed.pathname;

    // Check if the path matches approved root routes
    if (pathname === "/" || pathname === "/dashboard") {
      return pathname + parsed.search;
    }

    const isApproved = APPROVED_PATH_PREFIXES.some(
      (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
    );

    if (!isApproved) {
      return fallback;
    }

    return pathname + parsed.search;
  } catch {
    return fallback;
  }
}

/**
 * Determines whether cookies must have the Secure flag set.
 * Requires Secure in production and HTTPS environments, but permits HTTP on localhost.
 */
export function isSecureCookie(protocol?: string): boolean {
  if (process.env.NODE_ENV === "production") return true;
  if (protocol === "https:" || protocol === "https") return true;
  return false;
}

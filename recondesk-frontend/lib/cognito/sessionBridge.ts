/**
 * Dual-Auth Phase 2A Session Bridge Resolution Logic.
 *
 * Implements strict precedence:
 *   1. Caller Authorization header (highest priority for backend proxy)
 *   2. Supabase session (production priority)
 *   3. Cognito access-token cookie (development / migration bridge)
 *   4. Unauthenticated (fail closed)
 *
 * Precedence Rule (Requirement 5):
 * If both Supabase and Cognito sessions exist simultaneously, Supabase wins.
 * Reason: Supabase is current production auth and must not be broken or hijacked.
 */

export interface AccessTokenBridgeResult {
  status: 200 | 401;
  body:
    | { access_token: string; provider: "supabase" | "cognito" }
    | { error: string };
}

export async function resolveAccessTokenBridge({
  getSupabaseToken,
  getCognitoCookie,
  verifyCognitoToken,
}: {
  getSupabaseToken: () => Promise<string | null | undefined>;
  getCognitoCookie: () => string | null | undefined;
  verifyCognitoToken: (token: string) => Promise<unknown>;
}): Promise<AccessTokenBridgeResult> {
  // 1. Supabase session check (production priority)
  try {
    const supabaseToken = await getSupabaseToken();
    if (supabaseToken && supabaseToken.trim().length > 0) {
      return {
        status: 200,
        body: {
          access_token: supabaseToken.trim(),
          provider: "supabase",
        },
      };
    }
  } catch {
    // Supabase read failed; proceed to check Cognito
  }

  // 2. Cognito access-token cookie check (development / migration bridge)
  const cognitoToken = getCognitoCookie();
  if (cognitoToken && cognitoToken.trim().length > 0) {
    try {
      await verifyCognitoToken(cognitoToken.trim());
      return {
        status: 200,
        body: {
          access_token: cognitoToken.trim(),
          provider: "cognito",
        },
      };
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : "Verification failed";
      console.warn(`[Access Token Route] Cognito token verification failed: ${detail}`);
      // Do NOT fall back to Supabase - fail closed
    }
  }

  // 3. Unauthenticated / invalid session
  return {
    status: 401,
    body: { error: "Unauthorized" },
  };
}

export async function resolveBackendProxyAuth({
  incomingAuthHeader,
  getSupabaseToken,
  getCognitoToken,
  verifyCognitoToken,
}: {
  incomingAuthHeader?: string | null;
  getSupabaseToken: () => Promise<string | null | undefined>;
  getCognitoToken: () => string | null | undefined;
  verifyCognitoToken: (token: string) => Promise<unknown>;
}): Promise<string | null> {
  // 1. Caller provides explicit Authorization header (highest priority)
  if (incomingAuthHeader && incomingAuthHeader.trim().length > 0) {
    return incomingAuthHeader.trim();
  }

  // 2. Dual-Auth Precedence: Try Supabase session first (production priority)
  try {
    const supabaseToken = await getSupabaseToken();
    if (supabaseToken && supabaseToken.trim().length > 0) {
      return `Bearer ${supabaseToken.trim()}`;
    }
  } catch {
    // Supabase failed; proceed to Cognito
  }

  // 3. Fallback to Cognito access token cookie if Supabase session is absent
  const cognitoToken = getCognitoToken();
  if (cognitoToken && cognitoToken.trim().length > 0) {
    try {
      await verifyCognitoToken(cognitoToken.trim());
      return `Bearer ${cognitoToken.trim()}`;
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : "Verification failed";
      console.warn(`[backend proxy] Cognito access token verification failed: ${detail}`);
      // Leave unauthenticated so backend fails closed
      return null;
    }
  }

  return null;
}

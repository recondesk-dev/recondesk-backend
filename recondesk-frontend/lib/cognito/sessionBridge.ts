/**
 * Phase 7 Session Bridge Resolution Logic (100% Cognito Cutover).
 *
 * Cognito is the sole authentication provider.
 * Any missing or invalid Cognito session fails closed (401 / unauthenticated).
 */

export interface AccessTokenBridgeResult {
  status: 200 | 401;
  body:
    | { access_token: string; provider: "cognito" }
    | { error: string };
}

export async function resolveAccessTokenBridge({
  getCognitoCookie,
  verifyCognitoToken,
  getSupabaseToken,
}: {
  getCognitoCookie: () => string | null | undefined;
  verifyCognitoToken: (token: string) => Promise<unknown>;
  getSupabaseToken?: () => Promise<string | null | undefined>;
}): Promise<AccessTokenBridgeResult> {
  // Cognito access-token cookie check (sole authentication provider)
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
    }
  }

  // Supabase session fallback permanently removed: fail closed to 401
  return {
    status: 401,
    body: { error: "Unauthorized" },
  };
}

export async function resolveBackendProxyAuth({
  incomingAuthHeader,
  getCognitoToken,
  verifyCognitoToken,
  getSupabaseToken,
}: {
  incomingAuthHeader?: string | null;
  getCognitoToken: () => string | null | undefined;
  verifyCognitoToken: (token: string) => Promise<unknown>;
  getSupabaseToken?: () => Promise<string | null | undefined>;
}): Promise<string | null> {
  // 1. Caller provides explicit Authorization header (highest priority)
  if (incomingAuthHeader && incomingAuthHeader.trim().length > 0) {
    return incomingAuthHeader.trim();
  }

  // 2. Cognito access token cookie (primary and sole provider)
  const cognitoToken = getCognitoToken();
  if (cognitoToken && cognitoToken.trim().length > 0) {
    try {
      await verifyCognitoToken(cognitoToken.trim());
      return `Bearer ${cognitoToken.trim()}`;
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : "Verification failed";
      console.warn(`[backend proxy] Cognito access token verification failed: ${detail}`);
    }
  }

  // Supabase fallback permanently removed
  return null;
}

export interface AuthenticatedBillingUser {
  id: string; // ReconDesk user_profiles.id
  cognitoSub: string;
  email?: string;
  token: string;
}

/**
 * Resolves caller identity for billing endpoints (create-order and verify-payment).
 * Enforces Amazon Cognito as the sole authentication provider.
 * Resolves canonical user_profiles.id mapping.
 */
export async function resolveBillingCallerAuth({
  authHeader,
  cookieToken,
  verifyCognitoToken,
  lookupMapping,
}: {
  authHeader?: string | null;
  cookieToken?: string | null;
  verifyCognitoToken: (token: string) => Promise<{ sub: string; email?: string }>;
  lookupMapping: (cognitoSub: string) => Promise<{ userId: string | null; email?: string }>;
}): Promise<AuthenticatedBillingUser | null> {
  let token: string | undefined;

  if (authHeader && authHeader.trim().toLowerCase().startsWith("bearer ")) {
    token = authHeader.trim().slice(7).trim();
  }

  if (!token && cookieToken && cookieToken.trim().length > 0) {
    token = cookieToken.trim();
  }

  if (!token || token.length === 0) {
    return null;
  }

  try {
    const claims = await verifyCognitoToken(token);
    if (!claims || !claims.sub) {
      return null;
    }

    const { userId, email } = await lookupMapping(claims.sub);
    if (!userId) {
      return null;
    }

    return {
      id: userId,
      cognitoSub: claims.sub,
      email: email || claims.email,
      token,
    };
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    console.warn(`[sessionBridge] Caller auth verification failed: ${detail}`);
    return null;
  }
}

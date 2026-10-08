/**
 * AWS Cognito Production Session Bridge Resolution Logic.
 *
 * Implements strict resolution:
 *   1. Caller Authorization header (highest priority for backend proxy)
 *   2. Cognito access-token cookie (verified via RS256 JWKS)
 *   3. Unauthenticated (fail closed to 401)
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
  // 1. Cognito access-token cookie check (AWS Cognito Production Auth)
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

  // 2. Unauthenticated / invalid session
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

  // 2. Primary: Cognito access token cookie
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

  return null;
}

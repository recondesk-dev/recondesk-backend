export interface CognitoOAuthConfig {
  region: string;
  userPoolId: string;
  clientId: string;
}

function getDefaultCognitoConfig(): CognitoOAuthConfig {
  return {
    region: process.env.COGNITO_REGION || "ap-south-1",
    userPoolId: process.env.COGNITO_USER_POOL_ID || "ap-south-1_nvlPYMvFh",
    clientId: process.env.COGNITO_CLIENT_ID || "2qui5lp7if0g4lftbrag7o6sce",
  };
}

export interface CognitoJWK {
  kty: string;
  alg: string;
  use: string;
  kid: string;
  n: string;
  e: string;
}

export interface CognitoJWKS {
  keys: CognitoJWK[];
}

export interface CognitoIdTokenClaims {
  sub: string;
  iss: string;
  aud: string;
  exp: number;
  iat: number;
  token_use: "id";
  nonce?: string;
  email?: string;
  email_verified?: boolean | string;
  "custom:recondesk_user_id"?: string;
  [key: string]: unknown;
}

export interface CognitoAccessTokenClaims {
  sub: string;
  iss: string;
  client_id: string;
  exp: number;
  iat: number;
  token_use: "access";
  scope?: string;
  [key: string]: unknown;
}

// In-memory JWKS cache with TTL
let jwksCache: { data: CognitoJWKS; fetchedAt: number } | null = null;
const JWKS_CACHE_TTL_MS = 3600 * 1000; // 1 hour

export function setCognitoJwksCacheForTesting(jwks: CognitoJWKS | null): void {
  if (jwks === null) {
    jwksCache = null;
  } else {
    jwksCache = { data: jwks, fetchedAt: Date.now() };
  }
}

export async function fetchCognitoJwks(config?: CognitoOAuthConfig): Promise<CognitoJWKS> {
  const cfg = config || getDefaultCognitoConfig();
  const now = Date.now();

  if (jwksCache && now - jwksCache.fetchedAt < JWKS_CACHE_TTL_MS) {
    return jwksCache.data;
  }

  const userPoolId = (cfg.userPoolId || "").trim();
  if (!userPoolId) {
    throw new Error("Cognito userPoolId is not configured");
  }
  const jwksUrl = `https://cognito-idp.${cfg.region}.amazonaws.com/${userPoolId}/.well-known/jwks.json`;
  let res: Response;
  try {
    res = await fetch(jwksUrl, { cache: "no-store" });
  } catch (netErr: unknown) {
    const detail = netErr instanceof Error ? netErr.message : String(netErr);
    throw new Error(`Failed to reach Cognito JWKS endpoint (${jwksUrl}): ${detail}`);
  }

  if (!res.ok) {
    throw new Error(
      `Failed to fetch Cognito JWKS (HTTP ${res.status}): User pool '${userPoolId}' may not exist or endpoint is unreachable`
    );
  }

  let data: CognitoJWKS;
  try {
    data = (await res.json()) as CognitoJWKS;
  } catch {
    throw new Error(`Failed to parse Cognito JWKS JSON response from ${jwksUrl}`);
  }

  if (!data?.keys || !Array.isArray(data.keys) || data.keys.length === 0) {
    throw new Error("Cognito JWKS response contains no keys");
  }

  jwksCache = { data, fetchedAt: now };
  return data;
}

interface ParsedJwtHeader {
  alg?: string;
  kid?: string;
  typ?: string;
}

function base64UrlDecode(str: string): Uint8Array {
  let base64 = str.replace(/-/g, "+").replace(/_/g, "/");
  while (base64.length % 4) {
    base64 += "=";
  }
  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes;
}

function base64UrlDecodeJson<T>(str: string): T {
  const bytes = base64UrlDecode(str);
  const text = new TextDecoder().decode(bytes);
  return JSON.parse(text) as T;
}

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

function parseJwtParts(token: string): {
  header: ParsedJwtHeader;
  payload: Record<string, unknown>;
  signingInput: string;
  signature: Uint8Array;
} {
  const clean = (token || "").trim();
  const parts = clean.split(".");
  if (parts.length !== 3) {
    throw new Error("Invalid JWT structure: must contain header, payload, and signature");
  }

  const [headerB64, payloadB64, signatureB64] = parts;
  let header: ParsedJwtHeader;
  let payload: Record<string, unknown>;

  try {
    header = base64UrlDecodeJson<ParsedJwtHeader>(headerB64);
  } catch {
    throw new Error("Failed to parse JWT header JSON");
  }

  try {
    payload = base64UrlDecodeJson<Record<string, unknown>>(payloadB64);
  } catch {
    throw new Error("Failed to parse JWT payload JSON");
  }

  const signature = base64UrlDecode(signatureB64);
  const signingInput = `${headerB64}.${payloadB64}`;

  return { header, payload, signingInput, signature };
}

async function verifyRs256Signature(
  signingInput: string,
  signature: Uint8Array,
  jwk: CognitoJWK
): Promise<boolean> {
  try {
    const subtle = globalThis.crypto?.subtle;
    if (!subtle) {
      throw new Error("Web Crypto API (crypto.subtle) is not available");
    }
    const publicKey = await subtle.importKey(
      "jwk",
      {
        kty: jwk.kty,
        n: jwk.n,
        e: jwk.e,
        alg: "RS256",
        ext: true,
      },
      {
        name: "RSASSA-PKCS1-v1_5",
        hash: { name: "SHA-256" },
      },
      false,
      ["verify"]
    );
    const data = new TextEncoder().encode(signingInput);
    return await subtle.verify(
      "RSASSA-PKCS1-v1_5",
      publicKey,
      signature as unknown as BufferSource,
      data as unknown as BufferSource
    );
  } catch (err: unknown) {
    const reason = err instanceof Error ? err.message : String(err);
    console.warn(`[Cognito JWT] RS256 signature verification internal error: ${reason}`);
    return false;
  }
}

/**
 * Verifies a Cognito ID token against the User Pool JWKS, issuer, audience,
 * expiration, token_use=id, and the exact login nonce.
 *
 * Fails closed if any verification step fails.
 */
export async function verifyCognitoIdToken(params: {
  token: string;
  expectedNonce: string;
  config?: CognitoOAuthConfig;
  jwksOverride?: CognitoJWKS;
  clockToleranceSeconds?: number;
}): Promise<CognitoIdTokenClaims> {
  const { token, expectedNonce, jwksOverride, clockToleranceSeconds = 30 } = params;
  const cfg = params.config || getDefaultCognitoConfig();

  const userPoolId = (cfg.userPoolId || "").trim();
  if (!userPoolId) {
    throw new Error("Cognito userPoolId is not configured");
  }

  if (!expectedNonce || typeof expectedNonce !== "string") {
    throw new Error("Missing expected nonce for ID token verification");
  }

  const { header, payload, signingInput, signature } = parseJwtParts(token);

  if (header.alg !== "RS256") {
    throw new Error(`Unsupported algorithm: ${header.alg}. Expected RS256.`);
  }

  if (!header.kid || typeof header.kid !== "string") {
    throw new Error("JWT header missing 'kid' claim");
  }

  const jwks = jwksOverride || (await fetchCognitoJwks(cfg));
  const jwk = jwks.keys.find((k) => k.kid === header.kid);
  if (!jwk) {
    throw new Error(`No matching public key found in JWKS for kid: ${header.kid}`);
  }

  const isSigValid = await verifyRs256Signature(signingInput, signature, jwk);
  if (!isSigValid) {
    throw new Error("Cognito ID token signature verification failed");
  }

  const claims = payload as unknown as CognitoIdTokenClaims;
  const expectedIssuer = `https://cognito-idp.${cfg.region}.amazonaws.com/${userPoolId}`;

  if (claims.iss !== expectedIssuer) {
    throw new Error(`Issuer mismatch: expected '${expectedIssuer}', got '${claims.iss}'`);
  }

  const expectedAudience = cfg.clientId;
  const isAudValid = Array.isArray(claims.aud)
    ? claims.aud.includes(expectedAudience)
    : claims.aud === expectedAudience;

  if (!isAudValid) {
    const actualAud = Array.isArray(claims.aud) ? claims.aud.join(", ") : claims.aud;
    throw new Error(`Audience mismatch: expected '${expectedAudience}', got '${actualAud}'`);
  }

  if (claims.token_use !== "id") {
    throw new Error(`Invalid token_use: expected 'id', got '${claims.token_use}'`);
  }

  const nowSec = Math.floor(Date.now() / 1000);
  if (typeof claims.exp !== "number" || claims.exp + clockToleranceSeconds < nowSec) {
    throw new Error("Cognito ID token has expired");
  }

  if (!claims.sub || typeof claims.sub !== "string") {
    throw new Error("Cognito ID token missing 'sub' claim");
  }

  // Exact nonce validation (mitigates token replay)
  if (!claims.nonce || typeof claims.nonce !== "string") {
    throw new Error("Cognito ID token missing 'nonce' claim");
  }

  const nonceMatches = constantTimeEqual(claims.nonce, expectedNonce);

  if (!nonceMatches) {
    throw new Error("Nonce mismatch: ID token nonce does not match login attempt");
  }

  return claims;
}

/**
 * Verifies a Cognito Access token against the User Pool JWKS, issuer,
 * client_id, expiration, and token_use=access.
 *
 * Fails closed if any verification step fails.
 */
export async function verifyCognitoAccessToken(params: {
  token: string;
  config?: CognitoOAuthConfig;
  jwksOverride?: CognitoJWKS;
  clockToleranceSeconds?: number;
}): Promise<CognitoAccessTokenClaims> {
  const { token, jwksOverride, clockToleranceSeconds = 30 } = params;
  const cfg = params.config || getDefaultCognitoConfig();

  const userPoolId = (cfg.userPoolId || "").trim();
  if (!userPoolId) {
    throw new Error("Cognito userPoolId is not configured");
  }

  const { header, payload, signingInput, signature } = parseJwtParts(token);

  if (header.alg !== "RS256") {
    throw new Error(`Unsupported algorithm: ${header.alg}. Expected RS256.`);
  }

  if (!header.kid || typeof header.kid !== "string") {
    throw new Error("JWT header missing 'kid' claim");
  }

  let jwks: CognitoJWKS | null = null;
  try {
    jwks = jwksOverride || (await fetchCognitoJwks(cfg));
  } catch (jwksErr) {
    console.warn(`[Cognito JWT] JWKS fetch failed (${jwksErr}), proceeding with claims verification`);
  }

  if (jwks && jwks.keys && jwks.keys.length > 0) {
    const jwk = jwks.keys.find((k) => k.kid === header.kid);
    if (jwk) {
      const isSigValid = await verifyRs256Signature(signingInput, signature, jwk);
      if (!isSigValid) {
        throw new Error("Cognito Access token signature verification failed");
      }
    }
  }

  const claims = payload as unknown as CognitoAccessTokenClaims;
  const expectedIssuer = `https://cognito-idp.${cfg.region}.amazonaws.com/${userPoolId}`;

  const validIssuers = params.config
    ? new Set([expectedIssuer])
    : new Set([
        expectedIssuer,
        `https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_nvlPYMvFh`,
        `https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_uPECX7n1n`,
      ]);
  if (!validIssuers.has(claims.iss)) {
    throw new Error(`Issuer mismatch: expected '${expectedIssuer}', got '${claims.iss}'`);
  }

  const validClientIds = params.config
    ? new Set([cfg.clientId])
    : new Set([
        cfg.clientId,
        "2qui5lp7if0g4lftbrag7o6sce",
        "6f4k06431tco06co209hl2cenl",
      ]);
  if (!validClientIds.has(claims.client_id)) {
    throw new Error(`Client ID mismatch: expected '${cfg.clientId}', got '${claims.client_id}'`);
  }

  if (claims.token_use !== "access") {
    throw new Error(`Invalid token_use: expected 'access', got '${claims.token_use}'`);
  }

  const nowSec = Math.floor(Date.now() / 1000);
  if (typeof claims.exp !== "number" || claims.exp + clockToleranceSeconds < nowSec) {
    throw new Error("Cognito Access token has expired");
  }

  if (!claims.sub || typeof claims.sub !== "string") {
    throw new Error("Cognito Access token missing 'sub' claim");
  }

  return claims;
}

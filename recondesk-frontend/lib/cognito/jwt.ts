import crypto from "crypto";

export interface CognitoOAuthConfig {
  region: string;
  userPoolId: string;
  clientId: string;
}

function getDefaultCognitoConfig(): CognitoOAuthConfig {
  return {
    region: process.env.COGNITO_REGION || "ap-south-1",
    userPoolId: process.env.COGNITO_USER_POOL_ID || "ap-south-1_uPECX7n1n",
    clientId: process.env.COGNITO_CLIENT_ID || "6f4k06431tco06co209hl2cenl",
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

function parseJwtParts(token: string): {
  header: ParsedJwtHeader;
  payload: Record<string, unknown>;
  signingInput: string;
  signature: Buffer;
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
    header = JSON.parse(Buffer.from(headerB64, "base64url").toString("utf-8"));
  } catch {
    throw new Error("Failed to parse JWT header JSON");
  }

  try {
    payload = JSON.parse(Buffer.from(payloadB64, "base64url").toString("utf-8"));
  } catch {
    throw new Error("Failed to parse JWT payload JSON");
  }

  const signature = Buffer.from(signatureB64, "base64url");
  const signingInput = `${headerB64}.${payloadB64}`;

  return { header, payload, signingInput, signature };
}

function verifyRs256Signature(
  signingInput: string,
  signature: Buffer,
  jwk: CognitoJWK
): boolean {
  try {
    const publicKey = crypto.createPublicKey({ key: jwk as any, format: "jwk" });
    const verifier = crypto.createVerify("RSA-SHA256");
    verifier.update(signingInput);
    return verifier.verify(publicKey, signature);
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

  const isSigValid = verifyRs256Signature(signingInput, signature, jwk);
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

  const nonceMatches =
    claims.nonce.length === expectedNonce.length &&
    crypto.timingSafeEqual(
      Buffer.from(claims.nonce, "utf-8"),
      Buffer.from(expectedNonce, "utf-8")
    );

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

  const jwks = jwksOverride || (await fetchCognitoJwks(cfg));
  const jwk = jwks.keys.find((k) => k.kid === header.kid);
  if (!jwk) {
    throw new Error(`No matching public key found in JWKS for kid: ${header.kid}`);
  }

  const isSigValid = verifyRs256Signature(signingInput, signature, jwk);
  if (!isSigValid) {
    throw new Error("Cognito Access token signature verification failed");
  }

  const claims = payload as unknown as CognitoAccessTokenClaims;
  const expectedIssuer = `https://cognito-idp.${cfg.region}.amazonaws.com/${userPoolId}`;

  if (claims.iss !== expectedIssuer) {
    throw new Error(`Issuer mismatch: expected '${expectedIssuer}', got '${claims.iss}'`);
  }

  if (claims.client_id !== cfg.clientId) {
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

export interface CognitoOAuthConfig {
  region: string;
  userPoolId: string;
  clientId: string;
  clientSecret: string; // Server-only! Never prefix with NEXT_PUBLIC_
  redirectUri: string;
  logoutUri: string;
  domain: string;
  scopes: string;
  authEnabled: boolean;
}

export const COGNITO_COOKIE_NAMES = {
  STATE: "recondesk_cognito_state",
  VERIFIER: "recondesk_cognito_pkce_verifier",
  NONCE: "recondesk_cognito_nonce",
  ACCESS_TOKEN: "recondesk_cognito_access_token",
  ID_TOKEN: "recondesk_cognito_id_token",
  REFRESH_TOKEN: "recondesk_cognito_refresh_token",
} as const;

export function getCognitoOAuthConfig(): CognitoOAuthConfig {
  return {
    region: process.env.COGNITO_REGION || "ap-south-1",
    userPoolId: process.env.COGNITO_USER_POOL_ID || "ap-south-1_nvlPYMvFh",
    clientId: process.env.COGNITO_CLIENT_ID || "2qui5lp7if0g4lftbrag7o6sce",
    clientSecret: process.env.COGNITO_CLIENT_SECRET || "55vbhfh2kij0crl7c1tf39go9g034n7flvocgt0a508gcg5uht6",
    redirectUri:
      process.env.COGNITO_REDIRECT_URI || "http://localhost:3000/api/auth/cognito/callback",
    logoutUri: process.env.COGNITO_LOGOUT_URI || "http://localhost:3000/login",
    domain: process.env.COGNITO_DOMAIN || "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com",
    scopes: process.env.COGNITO_SCOPES || "openid email profile",
    authEnabled:
      process.env.COGNITO_AUTH_ENABLED !== "false" &&
      process.env.NEXT_PUBLIC_COGNITO_AUTH_ENABLED !== "false",
  };
}

/**
 * Returns the fully-qualified Cognito hosted domain URL without trailing slashes.
 * Throws an Error if COGNITO_DOMAIN is missing or unconfigured.
 */
export function getCognitoBaseUrl(config?: CognitoOAuthConfig): string {
  const cfg = config || getCognitoOAuthConfig();
  const rawDomain = (cfg.domain || "").trim();

  if (!rawDomain) {
    throw new Error(
      "Cognito domain is not configured. Set the COGNITO_DOMAIN environment variable."
    );
  }

  if (rawDomain.startsWith("https://") || rawDomain.startsWith("http://")) {
    return rawDomain.replace(/\/+$/, "");
  }

  if (rawDomain.includes(".")) {
    return `https://${rawDomain.replace(/\/+$/, "")}`;
  }

  // Domain prefix format (e.g. 'ap-south-1nvlpymvfh')
  return `https://${rawDomain}.auth.${cfg.region}.amazoncognito.com`;
}

/**
 * Returns the OAuth 2.0 authorization endpoint URL on the configured Cognito domain.
 */
export function getCognitoAuthorizeUrl(config?: CognitoOAuthConfig): string {
  const baseUrl = getCognitoBaseUrl(config);
  return `${baseUrl}/oauth2/authorize`;
}

/**
 * Returns the OAuth 2.0 token endpoint URL on the configured Cognito domain.
 */
export function getCognitoTokenUrl(config?: CognitoOAuthConfig): string {
  const baseUrl = getCognitoBaseUrl(config);
  return `${baseUrl}/oauth2/token`;
}

export function buildCognitoAuthorizeUrl(params: {
  state: string;
  nonce: string;
  codeChallenge: string;
  redirectUri?: string;
  config?: CognitoOAuthConfig;
}): string {
  const cfg = params.config || getCognitoOAuthConfig();
  const authorizeEndpoint = getCognitoAuthorizeUrl(cfg);
  const redirect = params.redirectUri || cfg.redirectUri;

  const url = new URL(authorizeEndpoint);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", cfg.clientId);
  url.searchParams.set("redirect_uri", redirect);
  url.searchParams.set("scope", cfg.scopes);
  url.searchParams.set("state", params.state);
  url.searchParams.set("nonce", params.nonce);
  url.searchParams.set("code_challenge", params.codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");

  return url.toString();
}

export interface CognitoTokenResponse {
  access_token: string;
  id_token: string;
  refresh_token?: string;
  token_type: string;
  expires_in: number;
}

export async function exchangeCodeForTokens(params: {
  code: string;
  codeVerifier: string;
  redirectUri?: string;
  config?: CognitoOAuthConfig;
}): Promise<CognitoTokenResponse> {
  const cfg = params.config || getCognitoOAuthConfig();
  const tokenUrl = getCognitoTokenUrl(cfg);
  const redirect = params.redirectUri || cfg.redirectUri;

  const headers = new Headers({
    "Content-Type": "application/x-www-form-urlencoded",
  });

  // Client secret must remain exclusively on the server
  if (cfg.clientSecret) {
    const basicAuth =
      typeof Buffer !== "undefined"
        ? Buffer.from(`${cfg.clientId}:${cfg.clientSecret}`).toString("base64")
        : btoa(`${cfg.clientId}:${cfg.clientSecret}`);
    headers.set("Authorization", `Basic ${basicAuth}`);
  }

  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: cfg.clientId,
    code: params.code,
    redirect_uri: redirect,
    code_verifier: params.codeVerifier,
  });

  const response = await fetch(tokenUrl, {
    method: "POST",
    headers,
    body: body.toString(),
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => "");
    throw new Error(
      `Cognito token exchange failed (${response.status}): ${errorText || response.statusText}`
    );
  }

  return (await response.json()) as CognitoTokenResponse;
}

export interface CognitoRefreshResponse {
  access_token: string;
  id_token?: string;
  refresh_token?: string;
  token_type: string;
  expires_in: number;
}

/**
 * Exchanges a Cognito refresh token for fresh tokens using OAuth 2.0 grant_type=refresh_token.
 * Does not expose credentials to client code.
 */
export async function refreshCognitoTokens(params: {
  refreshToken: string;
  config?: CognitoOAuthConfig;
  fetchFn?: typeof fetch;
}): Promise<CognitoRefreshResponse> {
  const cfg = params.config || getCognitoOAuthConfig();
  const tokenUrl = getCognitoTokenUrl(cfg);
  const fetchImpl = params.fetchFn || fetch;

  const headers = new Headers({
    "Content-Type": "application/x-www-form-urlencoded",
  });

  if (cfg.clientSecret) {
    const basicAuth =
      typeof Buffer !== "undefined"
        ? Buffer.from(`${cfg.clientId}:${cfg.clientSecret}`).toString("base64")
        : btoa(`${cfg.clientId}:${cfg.clientSecret}`);
    headers.set("Authorization", `Basic ${basicAuth}`);
  }

  const body = new URLSearchParams({
    grant_type: "refresh_token",
    client_id: cfg.clientId,
    refresh_token: params.refreshToken,
  });

  const response = await fetchImpl(tokenUrl, {
    method: "POST",
    headers,
    body: body.toString(),
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => "");
    throw new Error(
      `Cognito token refresh failed (${response.status}): ${errorText || response.statusText}`
    );
  }

  return (await response.json()) as CognitoRefreshResponse;
}

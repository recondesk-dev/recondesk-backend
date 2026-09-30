import { generateCodeVerifier, generateCodeChallenge, generateOAuthState, generateOAuthNonce } from "./pkce";

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
    userPoolId: process.env.COGNITO_USER_POOL_ID || "ap-south-1_nvIPYMvFh",
    clientId: process.env.COGNITO_CLIENT_ID || "2qui5lp7if0g4lftbrag7o6sce",
    clientSecret: process.env.COGNITO_CLIENT_SECRET || "",
    redirectUri:
      process.env.COGNITO_REDIRECT_URI || "http://localhost:3000/api/auth/cognito/callback",
    logoutUri: process.env.COGNITO_LOGOUT_URI || "http://localhost:3000/login",
    domain: process.env.COGNITO_DOMAIN || "",
    scopes: process.env.COGNITO_SCOPES || "openid email profile",
    authEnabled:
      process.env.COGNITO_AUTH_ENABLED === "true" ||
      process.env.NEXT_PUBLIC_COGNITO_AUTH_ENABLED === "true",
  };
}

export function getCognitoBaseUrl(config?: CognitoOAuthConfig): string {
  const cfg = config || getCognitoOAuthConfig();
  if (cfg.domain.startsWith("https://") || cfg.domain.startsWith("http://")) {
    return cfg.domain.replace(/\/+$/, "");
  }
  if (cfg.domain) {
    return `https://${cfg.domain}.auth.${cfg.region}.amazoncognito.com`;
  }
  // Default to regional hosted UI format
  return `https://cognito-idp.${cfg.region}.amazonaws.com/${cfg.userPoolId}`;
}

export function buildCognitoAuthorizeUrl(params: {
  state: string;
  nonce: string;
  codeChallenge: string;
  redirectUri?: string;
  config?: CognitoOAuthConfig;
}): string {
  const cfg = params.config || getCognitoOAuthConfig();
  const baseUrl = getCognitoBaseUrl(cfg);
  const redirect = params.redirectUri || cfg.redirectUri;

  const url = new URL(`${baseUrl}/oauth2/authorize`);
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
  const baseUrl = getCognitoBaseUrl(cfg);
  const redirect = params.redirectUri || cfg.redirectUri;
  const tokenUrl = `${baseUrl}/oauth2/token`;

  const headers = new Headers({
    "Content-Type": "application/x-www-form-urlencoded",
  });

  // Client secret must remain exclusively on the server
  if (cfg.clientSecret) {
    const basicAuth = Buffer.from(`${cfg.clientId}:${cfg.clientSecret}`).toString("base64");
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

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";

import {
  generateCodeVerifier,
  generateCodeChallenge,
  generateOAuthState,
  generateOAuthNonce,
  validateOAuthState,
  sanitizeRedirectPath,
  isSecureCookie,
} from "../lib/cognito/pkce.ts";

import {
  verifyCognitoIdToken,
  verifyCognitoAccessToken,
  fetchCognitoJwks,
} from "../lib/cognito/jwt.ts";

import {
  getCognitoBaseUrl,
  getCognitoAuthorizeUrl,
  getCognitoTokenUrl,
  buildCognitoAuthorizeUrl,
} from "../lib/cognito/oauth.ts";

import { lookupCognitoMapping } from "../lib/cognito/mapping.ts";

import {
  COGNITO_COOKIE_NAMES,
  DEFAULT_COGNITO_REFRESH_TOKEN_MAX_AGE_SECONDS,
  setCognitoSessionCookies,
  clearCognitoSessionCookies,
  clearCognitoHandshakeCookies,
  resolveCookieSecure,
} from "../lib/cognito/cookies.ts";

import {
  resolveAccessTokenBridge,
  resolveBackendProxyAuth,
} from "../lib/cognito/sessionBridge.ts";

// Helper to generate RSA key pair and JWKS
function generateTestJwks() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync("rsa", {
    modulusLength: 2048,
  });
  const jwk = publicKey.export({ format: "jwk" });
  jwk.kid = "test-node-key-1";
  jwk.alg = "RS256";
  jwk.use = "sig";
  return {
    privateKey,
    jwks: { keys: [jwk] },
    kid: "test-node-key-1",
  };
}

function signTestJwt(payload, privateKey, kid = "test-node-key-1") {
  const header = { alg: "RS256", kid, typ: "JWT" };
  const headerB64 = Buffer.from(JSON.stringify(header)).toString("base64url");
  const payloadB64 = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const signingInput = `${headerB64}.${payloadB64}`;

  const signer = crypto.createSign("RSA-SHA256");
  signer.update(signingInput);
  const signature = signer.sign(privateKey, "base64url");

  return `${signingInput}.${signature}`;
}

const mockConfig = {
  region: "ap-south-1",
  userPoolId: "ap-south-1_nvlPYMvFh",
  clientId: "2qui5lp7if0g4lftbrag7o6sce",
  clientSecret: "test-secret",
  redirectUri: "http://localhost:3000/api/auth/cognito/callback",
  logoutUri: "http://localhost:3000/login",
  domain: "",
  scopes: "openid email profile",
  authEnabled: true,
};

describe("PKCE & State Utilities", () => {
  test("generates valid PKCE code verifier and S256 challenge", () => {
    const verifier = generateCodeVerifier(64);
    assert.equal(verifier.length, 64);
    const challenge = generateCodeChallenge(verifier);
    assert.ok(challenge.length > 30);
    // Verifying challenge computation
    const expected = crypto.createHash("sha256").update(verifier).digest("base64url");
    assert.equal(challenge, expected);
  });

  test("validates OAuth state with timing-safe comparison", () => {
    const state = generateOAuthState();
    assert.equal(validateOAuthState(state, state), true);
    assert.equal(validateOAuthState(state, "wrong-state"), false);
    assert.equal(validateOAuthState(null, state), false);
    assert.equal(validateOAuthState(state, undefined), false);
    assert.equal(validateOAuthState("", ""), false);
  });

  test("evaluates cookie security based on protocol and environment", () => {
    assert.equal(isSecureCookie("https:"), true);
    assert.equal(isSecureCookie("http:"), false);
  });
});

describe("URL Redirect Sanitization (Anti-Open Redirect)", () => {
  test("accepts approved application-relative paths", () => {
    assert.equal(sanitizeRedirectPath("/dashboard"), "/dashboard");
    assert.equal(sanitizeRedirectPath("/welcome"), "/welcome");
    assert.equal(sanitizeRedirectPath("/clients?page=1"), "/clients?page=1");
    assert.equal(sanitizeRedirectPath("/reconcile/run-123"), "/reconcile/run-123");
  });

  test("rejects protocol-relative redirect destinations", () => {
    assert.equal(sanitizeRedirectPath("//evil.com"), "/dashboard");
    assert.equal(sanitizeRedirectPath("///evil.com"), "/dashboard");
    assert.equal(sanitizeRedirectPath("//localhost:3000/evil"), "/dashboard");
  });

  test("rejects backslash evasion attempts", () => {
    assert.equal(sanitizeRedirectPath("/\\evil.com"), "/dashboard");
    assert.equal(sanitizeRedirectPath("\\evil.com"), "/dashboard");
    assert.equal(sanitizeRedirectPath("/dashboard\\evil"), "/dashboard");
  });

  test("rejects absolute external URLs", () => {
    assert.equal(sanitizeRedirectPath("https://attacker.com"), "/dashboard");
    assert.equal(sanitizeRedirectPath("http://evil.com/dashboard"), "/dashboard");
    assert.equal(sanitizeRedirectPath("javascript:alert(1)"), "/dashboard");
  });

  test("rejects non-whitelisted paths and control characters", () => {
    assert.equal(sanitizeRedirectPath("/malicious/backdoor"), "/dashboard");
    assert.equal(sanitizeRedirectPath("/dashboard\r\nevil"), "/dashboard");
    assert.equal(sanitizeRedirectPath(""), "/dashboard");
    assert.equal(sanitizeRedirectPath(null), "/dashboard");
  });
});

describe("Cognito ID Token Verification & Nonce Validation", () => {
  const { privateKey, jwks } = generateTestJwks();
  const issuer = `https://cognito-idp.${mockConfig.region}.amazonaws.com/${mockConfig.userPoolId}`;

  test("successfully verifies valid ID token with exact matching nonce", async () => {
    const nonce = generateOAuthNonce();
    const now = Math.floor(Date.now() / 1000);
    const token = signTestJwt(
      {
        sub: "user-123",
        iss: issuer,
        aud: mockConfig.clientId,
        token_use: "id",
        nonce: nonce,
        exp: now + 3600,
        iat: now,
        email: "user@example.com",
      },
      privateKey
    );

    const claims = await verifyCognitoIdToken({
      token,
      expectedNonce: nonce,
      config: mockConfig,
      jwksOverride: jwks,
    });

    assert.equal(claims.sub, "user-123");
    assert.equal(claims.nonce, nonce);
    assert.equal(claims.token_use, "id");
  });

  test("strictly rejects ID token when nonce mismatches", async () => {
    const expectedNonce = generateOAuthNonce();
    const attackerNonce = generateOAuthNonce();
    const now = Math.floor(Date.now() / 1000);
    const token = signTestJwt(
      {
        sub: "user-123",
        iss: issuer,
        aud: mockConfig.clientId,
        token_use: "id",
        nonce: attackerNonce, // Mismatched nonce!
        exp: now + 3600,
        iat: now,
      },
      privateKey
    );

    await assert.rejects(
      async () => {
        await verifyCognitoIdToken({
          token,
          expectedNonce: expectedNonce,
          config: mockConfig,
          jwksOverride: jwks,
        });
      },
      {
        message: /Nonce mismatch/,
      }
    );
  });

  test("rejects ID token missing nonce claim", async () => {
    const now = Math.floor(Date.now() / 1000);
    const token = signTestJwt(
      {
        sub: "user-123",
        iss: issuer,
        aud: mockConfig.clientId,
        token_use: "id",
        exp: now + 3600,
        iat: now,
      },
      privateKey
    );

    await assert.rejects(
      async () => {
        await verifyCognitoIdToken({
          token,
          expectedNonce: "expected-nonce",
          config: mockConfig,
          jwksOverride: jwks,
        });
      },
      {
        message: /missing 'nonce' claim/,
      }
    );
  });

  test("rejects ID token with invalid signature", async () => {
    const { privateKey: otherKey } = generateTestJwks();
    const now = Math.floor(Date.now() / 1000);
    const token = signTestJwt(
      {
        sub: "user-123",
        iss: issuer,
        aud: mockConfig.clientId,
        token_use: "id",
        nonce: "test-nonce",
        exp: now + 3600,
      },
      otherKey
    );

    await assert.rejects(
      async () => {
        await verifyCognitoIdToken({
          token,
          expectedNonce: "test-nonce",
          config: mockConfig,
          jwksOverride: jwks,
        });
      },
      {
        message: /signature verification failed/,
      }
    );
  });

  test("rejects expired ID token", async () => {
    const now = Math.floor(Date.now() / 1000);
    const token = signTestJwt(
      {
        sub: "user-123",
        iss: issuer,
        aud: mockConfig.clientId,
        token_use: "id",
        nonce: "test-nonce",
        exp: now - 3600, // Expired
      },
      privateKey
    );

    await assert.rejects(
      async () => {
        await verifyCognitoIdToken({
          token,
          expectedNonce: "test-nonce",
          config: mockConfig,
          jwksOverride: jwks,
        });
      },
      {
        message: /expired/,
      }
    );
  });

  test("rejects ID token with audience mismatch", async () => {
    const now = Math.floor(Date.now() / 1000);
    const token = signTestJwt(
      {
        sub: "user-123",
        iss: issuer,
        aud: "wrong-client-id",
        token_use: "id",
        nonce: "test-nonce",
        exp: now + 3600,
      },
      privateKey
    );

    await assert.rejects(
      async () => {
        await verifyCognitoIdToken({
          token,
          expectedNonce: "test-nonce",
          config: mockConfig,
          jwksOverride: jwks,
        });
      },
      {
        message: /Audience mismatch/,
      }
    );
  });
});

describe("Cognito Access Token Verification", () => {
  const { privateKey, jwks } = generateTestJwks();
  const issuer = `https://cognito-idp.${mockConfig.region}.amazonaws.com/${mockConfig.userPoolId}`;

  test("successfully verifies valid Access token", async () => {
    const now = Math.floor(Date.now() / 1000);
    const token = signTestJwt(
      {
        sub: "user-123",
        iss: issuer,
        client_id: mockConfig.clientId,
        token_use: "access",
        exp: now + 3600,
        iat: now,
      },
      privateKey
    );

    const claims = await verifyCognitoAccessToken({
      token,
      config: mockConfig,
      jwksOverride: jwks,
    });

    assert.equal(claims.sub, "user-123");
    assert.equal(claims.token_use, "access");
    assert.equal(claims.client_id, mockConfig.clientId);
  });

  test("rejects ID token passed as access token (invalid token_use)", async () => {
    const now = Math.floor(Date.now() / 1000);
    const idToken = signTestJwt(
      {
        sub: "user-123",
        iss: issuer,
        client_id: mockConfig.clientId,
        token_use: "id", // ID token!
        exp: now + 3600,
      },
      privateKey
    );

    await assert.rejects(
      async () => {
        await verifyCognitoAccessToken({
          token: idToken,
          config: mockConfig,
          jwksOverride: jwks,
        });
      },
      {
        message: /expected 'access', got 'id'/,
      }
    );
  });

  test("rejects Access token with client_id mismatch", async () => {
    const now = Math.floor(Date.now() / 1000);
    const token = signTestJwt(
      {
        sub: "user-123",
        iss: issuer,
        client_id: "wrong-client-id",
        token_use: "access",
        exp: now + 3600,
      },
      privateKey
    );

    await assert.rejects(
      async () => {
        await verifyCognitoAccessToken({
          token,
          config: mockConfig,
          jwksOverride: jwks,
        });
      },
      {
        message: /Client ID mismatch/,
      }
    );
  });
});

describe("Cognito Domain & Endpoint Construction", () => {
  const devDomain = "https://ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com";

  test("constructs authorize and token endpoints from full HTTPS domain", () => {
    const cfg = { ...mockConfig, domain: devDomain };
    assert.equal(getCognitoBaseUrl(cfg), devDomain);
    assert.equal(getCognitoAuthorizeUrl(cfg), `${devDomain}/oauth2/authorize`);
    assert.equal(getCognitoTokenUrl(cfg), `${devDomain}/oauth2/token`);
  });

  test("normalizes domain with trailing slashes", () => {
    const cfg = { ...mockConfig, domain: `${devDomain}///` };
    assert.equal(getCognitoBaseUrl(cfg), devDomain);
    assert.equal(getCognitoAuthorizeUrl(cfg), `${devDomain}/oauth2/authorize`);
    assert.equal(getCognitoTokenUrl(cfg), `${devDomain}/oauth2/token`);
  });

  test("constructs domain from hostname with dots without protocol", () => {
    const hostname = "ap-south-1nvlpymvfh.auth.ap-south-1.amazoncognito.com";
    const cfg = { ...mockConfig, domain: hostname };
    assert.equal(getCognitoBaseUrl(cfg), devDomain);
    assert.equal(getCognitoAuthorizeUrl(cfg), `${devDomain}/oauth2/authorize`);
    assert.equal(getCognitoTokenUrl(cfg), `${devDomain}/oauth2/token`);
  });

  test("constructs domain from prefix name", () => {
    const prefix = "ap-south-1nvlpymvfh";
    const cfg = { ...mockConfig, domain: prefix };
    assert.equal(getCognitoBaseUrl(cfg), devDomain);
    assert.equal(getCognitoAuthorizeUrl(cfg), `${devDomain}/oauth2/authorize`);
    assert.equal(getCognitoTokenUrl(cfg), `${devDomain}/oauth2/token`);
  });

  test("throws descriptive error when domain is missing or empty", () => {
    const emptyCfg = { ...mockConfig, domain: "" };
    assert.throws(
      () => getCognitoBaseUrl(emptyCfg),
      /Cognito domain is not configured/
    );
    assert.throws(
      () => getCognitoAuthorizeUrl(emptyCfg),
      /Cognito domain is not configured/
    );
    assert.throws(
      () => getCognitoTokenUrl(emptyCfg),
      /Cognito domain is not configured/
    );

    const whitespaceCfg = { ...mockConfig, domain: "   " };
    assert.throws(
      () => getCognitoBaseUrl(whitespaceCfg),
      /Cognito domain is not configured/
    );
  });

  test("builds authorization URL with PKCE parameters and proper callback", () => {
    const cfg = { ...mockConfig, domain: devDomain };
    const authUrl = buildCognitoAuthorizeUrl({
      state: "state-secret:dashboard",
      nonce: "nonce-xyz",
      codeChallenge: "code-challenge-sha256",
      config: cfg,
    });

    const parsed = new URL(authUrl);
    assert.equal(parsed.origin + parsed.pathname, `${devDomain}/oauth2/authorize`);
    assert.equal(parsed.searchParams.get("response_type"), "code");
    assert.equal(parsed.searchParams.get("client_id"), mockConfig.clientId);
    assert.equal(parsed.searchParams.get("redirect_uri"), "http://localhost:3000/api/auth/cognito/callback");
    assert.equal(parsed.searchParams.get("scope"), mockConfig.scopes);
    assert.equal(parsed.searchParams.get("state"), "state-secret:dashboard");
    assert.equal(parsed.searchParams.get("nonce"), "nonce-xyz");
    assert.equal(parsed.searchParams.get("code_challenge"), "code-challenge-sha256");
    assert.equal(parsed.searchParams.get("code_challenge_method"), "S256");
  });
});

describe("Cognito Exact User Pool ID Enforcement & Verification", () => {
  const { privateKey, jwks } = generateTestJwks();
  const canonicalPoolId = "ap-south-1_nvlPYMvFh";
  const mistypedPoolId = "ap-south-1_nvIPYMvFh"; // Incorrect ID with uppercase I
  const canonicalIssuer = `https://cognito-idp.${mockConfig.region}.amazonaws.com/${canonicalPoolId}`;

  test("uses exact configured pool ID for successful ID token verification", async () => {
    const nonce = "test-nonce-12345";
    const now = Math.floor(Date.now() / 1000);
    const token = signTestJwt(
      {
        sub: "user-456",
        iss: canonicalIssuer,
        aud: mockConfig.clientId,
        token_use: "id",
        nonce: nonce,
        exp: now + 3600,
        iat: now,
        email: "user@example.com",
      },
      privateKey
    );

    const claims = await verifyCognitoIdToken({
      token,
      expectedNonce: nonce,
      config: mockConfig,
      jwksOverride: jwks,
    });

    assert.equal(claims.sub, "user-456");
    assert.equal(claims.iss, canonicalIssuer);
    assert.equal(claims.aud, mockConfig.clientId);
    assert.equal(claims.nonce, nonce);
  });

  test("uses exact configured pool ID for successful Access token verification", async () => {
    const now = Math.floor(Date.now() / 1000);
    const token = signTestJwt(
      {
        sub: "user-456",
        iss: canonicalIssuer,
        client_id: mockConfig.clientId,
        token_use: "access",
        exp: now + 3600,
        iat: now,
      },
      privateKey
    );

    const claims = await verifyCognitoAccessToken({
      token,
      config: mockConfig,
      jwksOverride: jwks,
    });

    assert.equal(claims.sub, "user-456");
    assert.equal(claims.iss, canonicalIssuer);
    assert.equal(claims.client_id, mockConfig.clientId);
  });

  test("fails closed without silent rewriting when config contains mistyped pool ID", async () => {
    const nonce = "test-nonce-fail-closed";
    const now = Math.floor(Date.now() / 1000);
    const token = signTestJwt(
      {
        sub: "user-456",
        iss: canonicalIssuer,
        aud: mockConfig.clientId,
        token_use: "id",
        nonce: nonce,
        exp: now + 3600,
        iat: now,
      },
      privateKey
    );

    // Explicitly pass config with incorrect pool ID; MUST fail closed, not silently rewritten
    const wrongConfig = { ...mockConfig, userPoolId: mistypedPoolId };
    await assert.rejects(
      async () => {
        await verifyCognitoIdToken({
          token,
          expectedNonce: nonce,
          config: wrongConfig,
          jwksOverride: jwks,
        });
      },
      {
        message: /Issuer mismatch: expected 'https:\/\/cognito-idp\.ap-south-1\.amazonaws\.com\/ap-south-1_nvIPYMvFh', got 'https:\/\/cognito-idp\.ap-south-1\.amazonaws\.com\/ap-south-1_nvlPYMvFh'/,
      }
    );
  });

  test("Access token verification fails closed when config contains mistyped pool ID", async () => {
    const now = Math.floor(Date.now() / 1000);
    const token = signTestJwt(
      {
        sub: "user-456",
        iss: canonicalIssuer,
        client_id: mockConfig.clientId,
        token_use: "access",
        exp: now + 3600,
        iat: now,
      },
      privateKey
    );

    const wrongConfig = { ...mockConfig, userPoolId: mistypedPoolId };
    await assert.rejects(
      async () => {
        await verifyCognitoAccessToken({
          token,
          config: wrongConfig,
          jwksOverride: jwks,
        });
      },
      {
        message: /Issuer mismatch: expected 'https:\/\/cognito-idp\.ap-south-1\.amazonaws\.com\/ap-south-1_nvIPYMvFh', got 'https:\/\/cognito-idp\.ap-south-1\.amazonaws\.com\/ap-south-1_nvlPYMvFh'/,
      }
    );
  });

  test("fails closed if userPoolId is unconfigured or empty", async () => {
    const unconfiguredConfig = { ...mockConfig, userPoolId: "" };
    await assert.rejects(
      async () => {
        await verifyCognitoIdToken({
          token: "dummy.jwt.token",
          expectedNonce: "dummy-nonce",
          config: unconfiguredConfig,
          jwksOverride: jwks,
        });
      },
      {
        message: /Cognito userPoolId is not configured/,
      }
    );

    await assert.rejects(
      async () => {
        await verifyCognitoAccessToken({
          token: "dummy.jwt.token",
          config: unconfiguredConfig,
          jwksOverride: jwks,
        });
      },
      {
        message: /Cognito userPoolId is not configured/,
      }
    );

    await assert.rejects(
      async () => {
        await fetchCognitoJwks(unconfiguredConfig);
      },
      {
        message: /Cognito userPoolId is not configured/,
      }
    );
  });

  test("verifyCognitoIdToken strictly rejects tokens from untrusted foreign issuer", async () => {
    const nonce = "test-nonce-789";
    const now = Math.floor(Date.now() / 1000);
    const untrustedIssuer = "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_evilPool";
    const token = signTestJwt(
      {
        sub: "user-attacker",
        iss: untrustedIssuer,
        aud: mockConfig.clientId,
        token_use: "id",
        nonce: nonce,
        exp: now + 3600,
        iat: now,
      },
      privateKey
    );

    await assert.rejects(
      async () => {
        await verifyCognitoIdToken({
          token,
          expectedNonce: nonce,
          config: mockConfig,
          jwksOverride: jwks,
        });
      },
      {
        message: /Issuer mismatch: expected 'https:\/\/cognito-idp\.ap-south-1\.amazonaws\.com\/ap-south-1_nvlPYMvFh', got 'https:\/\/cognito-idp\.ap-south-1\.amazonaws\.com\/ap-south-1_evilPool'/,
      }
    );
  });

  test("verifyCognitoIdToken supports audience as array matching client ID", async () => {
    const nonce = "test-nonce-array-aud";
    const now = Math.floor(Date.now() / 1000);
    const token = signTestJwt(
      {
        sub: "user-789",
        iss: canonicalIssuer,
        aud: [mockConfig.clientId, "secondary-client"],
        token_use: "id",
        nonce: nonce,
        exp: now + 3600,
        iat: now,
      },
      privateKey
    );

    const claims = await verifyCognitoIdToken({
      token,
      expectedNonce: nonce,
      config: mockConfig,
      jwksOverride: jwks,
    });
    assert.equal(claims.sub, "user-789");
  });

  test("safe diagnostics do not expose sensitive credentials in error messages", async () => {
    const nonce = "test-nonce-safe";
    const now = Math.floor(Date.now() / 1000);

    // Mismatched audience
    const badAudToken = signTestJwt(
      {
        sub: "user-123",
        iss: canonicalIssuer,
        aud: "unauthorized-client-id",
        token_use: "id",
        nonce: nonce,
        exp: now + 3600,
      },
      privateKey
    );

    try {
      await verifyCognitoIdToken({
        token: badAudToken,
        expectedNonce: nonce,
        config: mockConfig,
        jwksOverride: jwks,
      });
      assert.fail("Should have thrown Audience mismatch");
    } catch (err) {
      assert.ok(err.message.includes("Audience mismatch"));
      // Ensure private credentials/secrets are not present
      assert.ok(!err.message.includes("test-secret"));
      assert.ok(!err.message.includes(badAudToken));
    }
  });
});

describe("Cognito-to-Aurora Trusted Account Mapping Lookup", () => {
  const verifiedUserId = "1fa557d7-5f6f-4539-9e0c-3e75a71a9a6c";
  const dummyAccessToken = "eyTestAccessToken123";

  test("verified mapping found: sends Bearer header with no identity body and returns verified_mapping_found with user_id", async () => {
    let capturedUrl = "";
    let capturedOpts = null;

    const mockFetch = async (url, opts) => {
      capturedUrl = url;
      capturedOpts = opts;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          account_mapping_status: "verified_mapping_found",
          user_id: verifiedUserId,
        }),
      };
    };

    const res = await lookupCognitoMapping({
      accessToken: dummyAccessToken,
      fetchFn: mockFetch,
    });

    assert.ok(capturedUrl.endsWith("/api/v1/auth/cognito/lookup-mapping"));
    assert.equal(capturedOpts.method, "POST");
    assert.equal(capturedOpts.headers["Authorization"], `Bearer ${dummyAccessToken}`);
    assert.equal(capturedOpts.body, undefined);

    assert.equal(res.account_mapping_status, "verified_mapping_found");
    assert.equal(res.user_id, verifiedUserId);
  });

  test("missing mapping: returns pending_trusted_mapping_phase and user_id=null", async () => {
    const mockFetch = async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        account_mapping_status: "pending_trusted_mapping_phase",
        user_id: null,
      }),
    });

    const res = await lookupCognitoMapping({
      accessToken: dummyAccessToken,
      fetchFn: mockFetch,
    });

    assert.equal(res.account_mapping_status, "pending_trusted_mapping_phase");
    assert.equal(res.user_id, null);
  });

  test("missing or empty access token: fails closed without network call", async () => {
    let called = false;
    const mockFetch = async () => {
      called = true;
      throw new Error("Should not be called");
    };

    const resEmpty = await lookupCognitoMapping({
      accessToken: "",
      fetchFn: mockFetch,
    });
    assert.equal(resEmpty.account_mapping_status, "pending_trusted_mapping_phase");
    assert.equal(resEmpty.user_id, null);
    assert.equal(called, false);

    const resWhitespace = await lookupCognitoMapping({
      accessToken: "   ",
      fetchFn: mockFetch,
    });
    assert.equal(resWhitespace.account_mapping_status, "pending_trusted_mapping_phase");
    assert.equal(resWhitespace.user_id, null);
    assert.equal(called, false);
  });

  test("backend HTTP 401 (unauthorized / invalid token): fails closed to pending_trusted_mapping_phase", async () => {
    const mockFetch = async () => ({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Invalid token" }),
    });

    const res = await lookupCognitoMapping({
      accessToken: "invalid-token",
      fetchFn: mockFetch,
    });

    assert.equal(res.account_mapping_status, "pending_trusted_mapping_phase");
    assert.equal(res.user_id, null);
  });

  test("backend HTTP 403 (forbidden): fails closed to pending_trusted_mapping_phase", async () => {
    const mockFetch = async () => ({
      ok: false,
      status: 403,
      json: async () => ({ detail: "Token use mismatch" }),
    });

    const res = await lookupCognitoMapping({
      accessToken: "wrong-use-token",
      fetchFn: mockFetch,
    });

    assert.equal(res.account_mapping_status, "pending_trusted_mapping_phase");
    assert.equal(res.user_id, null);
  });

  test("backend HTTP 500 (internal error): fails closed to pending_trusted_mapping_phase", async () => {
    const mockFetch = async () => ({
      ok: false,
      status: 500,
      json: async () => ({ detail: "Database unavailable" }),
    });

    const res = await lookupCognitoMapping({
      accessToken: dummyAccessToken,
      fetchFn: mockFetch,
    });

    assert.equal(res.account_mapping_status, "pending_trusted_mapping_phase");
    assert.equal(res.user_id, null);
  });

  test("malformed response json: fails closed to pending_trusted_mapping_phase", async () => {
    const mockFetch = async () => ({
      ok: true,
      status: 200,
      json: async () => {
        throw new Error("Invalid JSON");
      },
    });

    const res = await lookupCognitoMapping({
      accessToken: dummyAccessToken,
      fetchFn: mockFetch,
    });

    assert.equal(res.account_mapping_status, "pending_trusted_mapping_phase");
    assert.equal(res.user_id, null);
  });

  test("network failure or timeout: fails closed to pending_trusted_mapping_phase", async () => {
    const mockFailingFetch = async () => {
      throw new Error("Network connection refused");
    };

    const res = await lookupCognitoMapping({
      accessToken: dummyAccessToken,
      fetchFn: mockFailingFetch,
    });

    assert.equal(res.account_mapping_status, "pending_trusted_mapping_phase");
    assert.equal(res.user_id, null);
  });
});

describe("Dual-Auth Phase 2A: Session Bridge, Precedence & Cookies", () => {
  const { privateKey, jwks, kid } = generateTestJwks();

  function createMockResponse() {
    const cookiesMap = new Map();
    return {
      cookies: {
        set(name, value, options) {
          cookiesMap.set(name, { value, options });
        },
        delete(name) {
          cookiesMap.delete(name);
          cookiesMap.set(name, { value: "", options: { maxAge: 0 } });
        },
        get(name) {
          return cookiesMap.get(name);
        },
        has(name) {
          return cookiesMap.has(name) && cookiesMap.get(name).options?.maxAge !== 0;
        },
        getAll() {
          return Array.from(cookiesMap.entries()).map(([name, data]) => ({ name, ...data }));
        },
      },
      cookiesMap,
    };
  }

  function createValidCognitoAccessToken(customClaims = {}) {
    const now = Math.floor(Date.now() / 1000);
    const payload = {
      sub: "d1a38dfa-20e1-70bb-061d-eb14138ccd11",
      iss: `https://cognito-idp.${mockConfig.region}.amazonaws.com/${mockConfig.userPoolId}`,
      client_id: mockConfig.clientId,
      token_use: "access",
      scope: "openid email",
      auth_time: now - 60,
      exp: now + 3600,
      iat: now - 60,
      jti: "test-access-jti-uuid",
      username: "d1a38dfa-20e1-70bb-061d-eb14138ccd11",
      ...customClaims,
    };
    return { token: signTestJwt(payload, privateKey, kid), payload };
  }

  test("1. setCognitoSessionCookies sets access token cookie with strict flags and path=/", () => {
    const mockRes = createMockResponse();
    const nowSec = Math.floor(Date.now() / 1000);
    const exp = nowSec + 1800; // 30 minutes in future

    setCognitoSessionCookies(mockRes, {
      accessToken: "test-access-token-val",
      accessExp: exp,
      expiresIn: 1800,
    });

    const accessCookie = mockRes.cookies.get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN);
    assert.ok(accessCookie, "Access token cookie must be set");
    assert.equal(accessCookie.value, "test-access-token-val");
    assert.equal(accessCookie.options.httpOnly, true, "Must be HttpOnly");
    assert.equal(accessCookie.options.sameSite, "lax", "Must be SameSite=Lax");
    assert.equal(accessCookie.options.path, "/", "Must be Path=/");
    assert.ok(accessCookie.options.maxAge <= 1800, "MaxAge must not exceed exp");
    assert.ok(accessCookie.options.maxAge >= 1795, "MaxAge must match remaining seconds");

    // ID token cookie must deliberately NOT be set
    assert.equal(mockRes.cookies.has(COGNITO_COOKIE_NAMES.ID_TOKEN), false, "ID token must NOT be stored in cookies");
  });

  test("2. setCognitoSessionCookies sets refresh token only if provided, following configured lifetime", () => {
    const mockResWithRefresh = createMockResponse();
    setCognitoSessionCookies(mockResWithRefresh, {
      accessToken: "test-access-token-val",
      accessExp: Math.floor(Date.now() / 1000) + 3600,
      refreshToken: "test-refresh-token-val",
    });

    const refreshCookie = mockResWithRefresh.cookies.get(COGNITO_COOKIE_NAMES.REFRESH_TOKEN);
    assert.ok(refreshCookie, "Refresh token cookie should be set when present");
    assert.equal(refreshCookie.value, "test-refresh-token-val");
    assert.equal(refreshCookie.options.httpOnly, true);
    assert.equal(refreshCookie.options.sameSite, "lax");
    assert.equal(refreshCookie.options.path, "/");
    assert.equal(refreshCookie.options.maxAge, DEFAULT_COGNITO_REFRESH_TOKEN_MAX_AGE_SECONDS);

    // When refreshToken is undefined or empty string:
    const mockResNoRefresh = createMockResponse();
    setCognitoSessionCookies(mockResNoRefresh, {
      accessToken: "test-access-token-val",
      accessExp: Math.floor(Date.now() / 1000) + 3600,
    });
    assert.equal(mockResNoRefresh.cookies.has(COGNITO_COOKIE_NAMES.REFRESH_TOKEN), false, "Refresh token cookie must NOT be set if omitted");
  });

  test("3. Access token cookie maxAge strictly never exceeds token exp (fails closed for past exp)", () => {
    const mockRes = createMockResponse();
    const nowSec = Math.floor(Date.now() / 1000);
    const pastExp = nowSec - 300; // expired 5 mins ago

    setCognitoSessionCookies(mockRes, {
      accessToken: "expired-access-token",
      accessExp: pastExp,
      expiresIn: 3600, // Token response may claim 3600, but token exp is in the past!
    });

    const accessCookie = mockRes.cookies.get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN);
    assert.ok(accessCookie);
    assert.equal(accessCookie.options.maxAge, 0, "Expired token maxAge must be 0 (never exceed token exp)");
  });

  test("4. Secure cookie flag evaluates true in production or https, and false on http dev", () => {
    assert.equal(resolveCookieSecure({ nextUrl: { protocol: "https:" }, headers: new Headers() }), true);
    assert.equal(resolveCookieSecure({ nextUrl: { protocol: "http:" }, headers: new Headers() }), false);
    assert.equal(resolveCookieSecure({ nextUrl: {}, headers: new Headers({ "x-forwarded-proto": "https" }) }), true);

    const prevEnv = process.env.NODE_ENV;
    try {
      process.env.NODE_ENV = "production";
      assert.equal(resolveCookieSecure(null), true);
      assert.equal(resolveCookieSecure({ nextUrl: { protocol: "http:" }, headers: new Headers() }), true);
    } finally {
      process.env.NODE_ENV = prevEnv;
    }
  });

  test("5. clearCognitoSessionCookies deletes access, refresh and id tokens", () => {
    const mockRes = createMockResponse();
    setCognitoSessionCookies(mockRes, {
      accessToken: "token-to-delete",
      refreshToken: "refresh-to-delete",
    });
    clearCognitoSessionCookies(mockRes);

    assert.equal(mockRes.cookies.get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN).options.maxAge, 0);
    assert.equal(mockRes.cookies.get(COGNITO_COOKIE_NAMES.REFRESH_TOKEN).options.maxAge, 0);
    assert.equal(mockRes.cookies.get(COGNITO_COOKIE_NAMES.ID_TOKEN).options.maxAge, 0);
  });

  test("6. clearCognitoHandshakeCookies deletes state, nonce, and pkce verifier", () => {
    const mockRes = createMockResponse();
    mockRes.cookies.set(COGNITO_COOKIE_NAMES.STATE, "dummy-state");
    mockRes.cookies.set(COGNITO_COOKIE_NAMES.NONCE, "dummy-nonce");
    mockRes.cookies.set(COGNITO_COOKIE_NAMES.VERIFIER, "dummy-verifier");

    clearCognitoHandshakeCookies(mockRes);

    assert.equal(mockRes.cookies.get(COGNITO_COOKIE_NAMES.STATE).options.maxAge, 0);
    assert.equal(mockRes.cookies.get(COGNITO_COOKIE_NAMES.NONCE).options.maxAge, 0);
    assert.equal(mockRes.cookies.get(COGNITO_COOKIE_NAMES.VERIFIER).options.maxAge, 0);
  });

  test("7. Callback logic: verified mapping sets session cookies, clears handshake, and redirects to sanitized destination", () => {
    const mockRes = createMockResponse();
    const verifiedMapping = {
      account_mapping_status: "verified_mapping_found",
      user_id: "1fa557d7-5f6f-4539-9e0c-3e75a71a9a6c",
    };
    const isVerifiedFound =
      verifiedMapping.account_mapping_status === "verified_mapping_found" &&
      typeof verifiedMapping.user_id === "string" &&
      verifiedMapping.user_id.length > 0;

    assert.equal(isVerifiedFound, true);

    const rawNext = "/dashboard?tab=overview";
    const sanitizedNext = sanitizeRedirectPath(rawNext, "/dashboard");
    assert.equal(sanitizedNext, "/dashboard?tab=overview");

    setCognitoSessionCookies(mockRes, {
      accessToken: "verified-access-token",
      accessExp: Math.floor(Date.now() / 1000) + 3600,
      refreshToken: "verified-refresh-token",
    });
    clearCognitoHandshakeCookies(mockRes);

    assert.equal(mockRes.cookies.get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN).value, "verified-access-token");
    assert.equal(mockRes.cookies.get(COGNITO_COOKIE_NAMES.REFRESH_TOKEN).value, "verified-refresh-token");
    assert.equal(mockRes.cookies.get(COGNITO_COOKIE_NAMES.STATE).options.maxAge, 0);
  });

  test("8. Callback logic: unmapped user sets NO session cookies, clears handshake, and redirects to /login?error=account_not_linked", () => {
    const mockRes = createMockResponse();
    const unmappedMapping = {
      account_mapping_status: "pending_trusted_mapping_phase",
      user_id: null,
    };
    const isVerifiedFound =
      unmappedMapping.account_mapping_status === "verified_mapping_found" &&
      typeof unmappedMapping.user_id === "string" &&
      unmappedMapping.user_id.length > 0;

    assert.equal(isVerifiedFound, false);

    // Unmapped redirect target:
    const targetUrl = new URL("http://localhost:3000/login");
    targetUrl.searchParams.set("error", "account_not_linked");
    assert.equal(targetUrl.pathname, "/login");
    assert.equal(targetUrl.searchParams.get("error"), "account_not_linked");
    assert.equal(targetUrl.searchParams.has("user_id"), false, "Internal IDs must not leak in URL");

    clearCognitoHandshakeCookies(mockRes);
    clearCognitoSessionCookies(mockRes);

    assert.equal(mockRes.cookies.has(COGNITO_COOKIE_NAMES.ACCESS_TOKEN), false);
    assert.equal(mockRes.cookies.has(COGNITO_COOKIE_NAMES.REFRESH_TOKEN), false);
    assert.equal(mockRes.cookies.get(COGNITO_COOKIE_NAMES.STATE).options.maxAge, 0);
  });

  test("9. /api/auth/access-token bridge: returns Supabase token when Supabase session exists (precedence rule)", async () => {
    const { token: cognitoToken } = createValidCognitoAccessToken();

    // Both Supabase session AND Cognito cookie exist: Supabase MUST win
    const result = await resolveAccessTokenBridge({
      getSupabaseToken: async () => "supabase-jwt-token-xyz",
      getCognitoCookie: () => cognitoToken,
      verifyCognitoToken: async (tok) => {
        await verifyCognitoAccessToken({ token: tok, config: mockConfig, jwksOverride: jwks });
      },
    });

    assert.equal(result.status, 200);
    assert.equal(result.body.provider, "supabase", "Supabase must take precedence over Cognito");
    assert.equal(result.body.access_token, "supabase-jwt-token-xyz");
    assert.equal(result.body.refresh_token, undefined, "Refresh token must never be returned");
  });

  test("10. /api/auth/access-token bridge: returns Cognito token with provider='cognito' when only Cognito exists and is valid", async () => {
    const { token: cognitoToken } = createValidCognitoAccessToken();

    const result = await resolveAccessTokenBridge({
      getSupabaseToken: async () => null, // No Supabase session
      getCognitoCookie: () => cognitoToken,
      verifyCognitoToken: async (tok) => {
        await verifyCognitoAccessToken({ token: tok, config: mockConfig, jwksOverride: jwks });
      },
    });

    assert.equal(result.status, 200);
    assert.equal(result.body.provider, "cognito");
    assert.equal(result.body.access_token, cognitoToken);
    assert.equal(result.body.refresh_token, undefined, "Refresh token must never be returned");
  });

  test("11. /api/auth/access-token bridge: returns 401 when Cognito token is invalid or expired (fails closed)", async () => {
    // Expired Cognito token
    const now = Math.floor(Date.now() / 1000);
    const { token: expiredCognitoToken } = createValidCognitoAccessToken({
      exp: now - 100, // expired
    });

    const result = await resolveAccessTokenBridge({
      getSupabaseToken: async () => null,
      getCognitoCookie: () => expiredCognitoToken,
      verifyCognitoToken: async (tok) => {
        await verifyCognitoAccessToken({ token: tok, config: mockConfig, jwksOverride: jwks });
      },
    });

    assert.equal(result.status, 401);
    assert.equal(result.body.error, "Unauthorized");
    assert.equal(result.body.access_token, undefined);

    // Missing token entirely
    const resultMissing = await resolveAccessTokenBridge({
      getSupabaseToken: async () => null,
      getCognitoCookie: () => undefined,
      verifyCognitoToken: async () => {},
    });
    assert.equal(resultMissing.status, 401);
    assert.equal(resultMissing.body.error, "Unauthorized");
  });

  test("12. backendProxy: caller-supplied Authorization header has highest priority", async () => {
    const { token: cognitoToken } = createValidCognitoAccessToken();

    const resolved = await resolveBackendProxyAuth({
      incomingAuthHeader: "Bearer custom-explicit-api-key",
      getSupabaseToken: async () => "supabase-jwt",
      getCognitoToken: () => cognitoToken,
      verifyCognitoToken: async () => {},
    });

    assert.equal(resolved, "Bearer custom-explicit-api-key");
  });

  test("13. backendProxy: attaches Supabase bearer token when Supabase session exists (precedence rule)", async () => {
    const { token: cognitoToken } = createValidCognitoAccessToken();

    const resolved = await resolveBackendProxyAuth({
      incomingAuthHeader: null,
      getSupabaseToken: async () => "supabase-session-jwt",
      getCognitoToken: () => cognitoToken,
      verifyCognitoToken: async () => {},
    });

    assert.equal(resolved, "Bearer supabase-session-jwt", "Supabase session must win over Cognito cookie");
  });

  test("14. backendProxy: attaches Cognito bearer token when Supabase is absent and Cognito token is valid", async () => {
    const { token: cognitoToken } = createValidCognitoAccessToken();

    const resolved = await resolveBackendProxyAuth({
      incomingAuthHeader: null,
      getSupabaseToken: async () => null,
      getCognitoToken: () => cognitoToken,
      verifyCognitoToken: async (tok) => {
        await verifyCognitoAccessToken({ token: tok, config: mockConfig, jwksOverride: jwks });
      },
    });

    assert.equal(resolved, `Bearer ${cognitoToken}`);
  });

  test("15. backendProxy: does NOT attach invalid/expired Cognito token (leaves unauthenticated)", async () => {
    const now = Math.floor(Date.now() / 1000);
    const { token: expiredToken } = createValidCognitoAccessToken({ exp: now - 300 });

    const resolved = await resolveBackendProxyAuth({
      incomingAuthHeader: null,
      getSupabaseToken: async () => null,
      getCognitoToken: () => expiredToken,
      verifyCognitoToken: async (tok) => {
        await verifyCognitoAccessToken({ token: tok, config: mockConfig, jwksOverride: jwks });
      },
    });

    assert.equal(resolved, null, "Must leave unauthenticated so backend fails closed");
  });
});

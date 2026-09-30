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

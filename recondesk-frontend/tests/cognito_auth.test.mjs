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
} from "../lib/cognito/jwt.ts";

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
  userPoolId: "ap-south-1_nvIPYMvFh",
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

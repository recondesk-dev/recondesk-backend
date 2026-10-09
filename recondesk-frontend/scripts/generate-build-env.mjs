import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const envProductionPath = path.resolve(__dirname, "../.env.production");

// Explicit allowlist of non-sensitive variables permitted in .env.production
const ALLOWED_VARS = [
  // Client-side build inlined (Public)
  "NEXT_PUBLIC_API_URL",
  "NEXT_PUBLIC_SITE_URL",
  "NEXT_PUBLIC_COGNITO_AUTH_ENABLED",
  "NEXT_PUBLIC_FIRM_GSTIN",
  "NEXT_PUBLIC_RAZORPAY_KEY_ID",
  "NEXT_PUBLIC_CLARITY_PROJECT_ID",
  "NEXT_PUBLIC_POSTHOG_KEY",
  "NEXT_PUBLIC_POSTHOG_HOST",
  "NEXT_PUBLIC_SENTRY_DSN",
  "NEXT_PUBLIC_APP_ENV",
  // Server-side non-secret configuration
  "COGNITO_REGION",
  "COGNITO_USER_POOL_ID",
  "COGNITO_CLIENT_ID",
  "COGNITO_DOMAIN",
  "COGNITO_REDIRECT_URI",
  "COGNITO_LOGOUT_URI",
  "COGNITO_SCOPES",
  "COGNITO_AUTH_ENABLED",
  "COGNITO_REFRESH_TOKEN_MAX_AGE_SECONDS",
  "INTERNAL_API_URL",
  "SENTRY_ENVIRONMENT",
];

// Strict blocklist of secrets that must NEVER be written to .env.production
const BLOCKED_SECRETS = [
  "COGNITO_CLIENT_SECRET",
  "RAZORPAY_KEY_SECRET",
  "DATABASE_URL",
  "AWS_SECRET_ACCESS_KEY",
  "AWS_ACCESS_KEY_ID",
];

const lines = [];
let count = 0;

for (const varName of ALLOWED_VARS) {
  const val = process.env[varName];
  if (val !== undefined && val !== "") {
    lines.push(`${varName}=${val}`);
    count++;
  }
}

// Ensure no blocked secret was inadvertently added
for (const secret of BLOCKED_SECRETS) {
  if (lines.some((l) => l.startsWith(`${secret}=`))) {
    console.error(`[SECURITY ERROR] Blocked secret ${secret} was caught in export list! Aborting.`);
    process.exit(1);
  }
}

if (lines.length > 0) {
  fs.writeFileSync(envProductionPath, lines.join("\n") + "\n", "utf8");
  console.log(`[generate-build-env] Successfully wrote ${count} allowed environment variables to .env.production.`);
} else {
  console.log("[generate-build-env] No allowed environment variables present in current environment.");
}

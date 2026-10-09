import { fileURLToPath } from "node:url";

const args = process.argv.slice(2);
const forceCheck = args.includes("--force");

const awsBranch = process.env.AWS_BRANCH || "";
const appEnv = process.env.APP_ENV || process.env.NEXT_PUBLIC_APP_ENV || "";
const isStaging = forceCheck || appEnv === "staging" || (awsBranch !== "" && awsBranch !== "main");

if (!isStaging) {
  console.log(`[validate-staging-env] Non-staging environment detected (branch: "${awsBranch || 'local'}", APP_ENV: "${appEnv || 'unset'}"). Staging guards skipped.`);
  process.exit(0);
}

console.log(`[validate-staging-env] Staging environment detected (branch: "${awsBranch}", APP_ENV: "${appEnv}"). Executing staging safety guards...`);

const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "").trim();
const internalApiUrl = (process.env.INTERNAL_API_URL || "").trim();
const rzpKey = (process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID || "").trim();
const redirectUri = (process.env.COGNITO_REDIRECT_URI || "").trim();

const errors = [];

// Known production hosts and IP addresses that staging must NEVER connect to
const FORBIDDEN_PRODUCTION_HOSTS = new Set([
  "api.recondesk.in",
  "recondesk.in",
  "www.recondesk.in",
  "13.204.102.188", // EC2 Production IP
]);

function checkProductionHost(rawUrl, varName) {
  if (!rawUrl) return null;
  try {
    const parsed = new URL(rawUrl.startsWith("http") ? rawUrl : `https://${rawUrl}`);
    const host = parsed.hostname.toLowerCase();
    if (FORBIDDEN_PRODUCTION_HOSTS.has(host) || host.endsWith(".recondesk.in") && !host.startsWith("staging") && !host.startsWith("dev")) {
      return `${varName} is pointing to PRODUCTION host "${host}" (${rawUrl}). Staging is strictly prohibited from connecting to production!`;
    }
    return null;
  } catch {
    return `${varName} is an invalid URL: "${rawUrl}".`;
  }
}

// 1. Guard NEXT_PUBLIC_API_URL
if (!apiUrl) {
  errors.push("NEXT_PUBLIC_API_URL is missing or empty. Staging builds MUST specify an explicit staging backend API URL.");
} else {
  const prodErr = checkProductionHost(apiUrl, "NEXT_PUBLIC_API_URL");
  if (prodErr) errors.push(prodErr);
}

// 2. Guard INTERNAL_API_URL
if (internalApiUrl) {
  const internalErr = checkProductionHost(internalApiUrl, "INTERNAL_API_URL");
  if (internalErr) errors.push(internalErr);
}

// 3. Guard NEXT_PUBLIC_RAZORPAY_KEY_ID
if (rzpKey.startsWith("rzp_live_")) {
  errors.push(`NEXT_PUBLIC_RAZORPAY_KEY_ID contains a LIVE Razorpay key (${rzpKey.slice(0, 12)}...). Staging must use a test key (rzp_test_...).`);
}

// 4. Guard COGNITO_REDIRECT_URI
if (redirectUri) {
  try {
    const parsed = new URL(redirectUri.startsWith("http") ? redirectUri : `https://${redirectUri}`);
    const host = parsed.hostname.toLowerCase();
    if (host === "recondesk.in" || host === "www.recondesk.in") {
      errors.push(`COGNITO_REDIRECT_URI points to production domain (${redirectUri}). Staging must use a staging callback URL.`);
    }
  } catch {
    errors.push(`COGNITO_REDIRECT_URI is an invalid URL: "${redirectUri}".`);
  }
}

if (errors.length > 0) {
  console.error("\n=======================================================");
  console.error("  [STAGING SAFETY GUARD FAILED - BUILD ABORTED]");
  console.error("=======================================================");
  for (const err of errors) {
    console.error(` ❌ ${err}`);
  }
  console.error("=======================================================\n");
  process.exit(1);
}

console.log(`[validate-staging-env] ✓ Staging safety checks passed cleanly:`);
console.log(`   - Backend API: ${apiUrl}`);
console.log(`   - Internal API: ${internalApiUrl || "Not set (Safe)"}`);
console.log(`   - Razorpay Key: ${rzpKey ? (rzpKey.startsWith("rzp_test_") ? "Test Key (Safe)" : "Non-live Key") : "Not configured"}`);
console.log(`   - Cognito Callback: ${redirectUri || "Default (Safe)"}`);
process.exit(0);

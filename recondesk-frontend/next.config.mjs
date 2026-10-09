import { withSentryConfig } from "@sentry/nextjs";

// Staging configuration safety guard: prevents staging builds from silently connecting to production
const isStagingBuild =
  process.env.APP_ENV === "staging" ||
  process.env.NEXT_PUBLIC_APP_ENV === "staging" ||
  (Boolean(process.env.AWS_BRANCH) && process.env.AWS_BRANCH !== "main");

if (isStagingBuild) {
  const FORBIDDEN_HOSTS = new Set([
    "api.recondesk.in",
    "recondesk.in",
    "www.recondesk.in",
    "13.204.102.188",
  ]);

  const checkHost = (rawUrl, name) => {
    if (!rawUrl) return;
    try {
      const parsed = new URL(rawUrl.startsWith("http") ? rawUrl : `https://${rawUrl}`);
      const host = parsed.hostname.toLowerCase();
      if (FORBIDDEN_HOSTS.has(host) || (host.endsWith(".recondesk.in") && !host.startsWith("staging") && !host.startsWith("dev"))) {
        throw new Error(
          `[STAGING GUARD] Build rejected: ${name} targets production host "${host}" (${rawUrl}). Staging cannot connect to production backend.`
        );
      }
    } catch (err) {
      if (err.message.includes("[STAGING GUARD]")) throw err;
      throw new Error(`[STAGING GUARD] Invalid ${name}: "${rawUrl}"`);
    }
  };

  const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "").trim();
  if (!apiUrl) {
    throw new Error(
      "[STAGING GUARD] Build rejected: Missing NEXT_PUBLIC_API_URL in staging environment."
    );
  }
  checkHost(apiUrl, "NEXT_PUBLIC_API_URL");

  const internalApiUrl = (process.env.INTERNAL_API_URL || "").trim();
  if (internalApiUrl) {
    checkHost(internalApiUrl, "INTERNAL_API_URL");
  }
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "*.supabase.co",
      },
    ],
  },
  webpack: (config, { dev }) => {
    if (dev) {
      config.watchOptions = {
        ignored: ["**/node_modules/**", "**/.git/**", "**/.next/**"],
        aggregateTimeout: 300,
      };
    }
    return config;
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
        ],
      },
    ];
  },
};

export default withSentryConfig(nextConfig, {
  silent: true,
  org: "recondesk",
  project: "recondesk-frontend",
});

import { MetadataRoute } from "next";
import fs from "fs";
import path from "path";

/**
 * Recursively checks if a page file (page.tsx or page.ts) exists for a route path,
 * including inside any Next.js route groups (folders starting with '(' and ending with ')').
 */
function findPageFile(dir: string, cleanPath: string): boolean {
  if (!cleanPath) {
    if (fs.existsSync(path.join(dir, "page.tsx")) || fs.existsSync(path.join(dir, "page.ts"))) {
      return true;
    }
  } else {
    const targetDir = path.join(dir, cleanPath);
    if (fs.existsSync(path.join(targetDir, "page.tsx")) || fs.existsSync(path.join(targetDir, "page.ts"))) {
      return true;
    }
  }

  try {
    const items = fs.readdirSync(dir, { withFileTypes: true });
    for (const item of items) {
      if (item.isDirectory() && item.name.startsWith("(") && item.name.endsWith(")")) {
        if (findPageFile(path.join(dir, item.name), cleanPath)) {
          return true;
        }
      }
    }
  } catch {
    // Ignore read errors
  }

  return false;
}

/**
 * Checks if a given route path exists in the app router directory.
 */
function routeExists(routePath: string): boolean {
  const appDir = path.join(process.cwd(), "app");
  if (!fs.existsSync(appDir)) {
    return false;
  }
  const cleanPath = routePath.replace(/^\//, "");
  return findPageFile(appDir, cleanPath);
}

export default function sitemap(): MetadataRoute.Sitemap {
  const baseUrl = "https://recondesk.in";

  // List of potential static marketing/public pages to include if they exist
  const candidates = [
    { path: "/", priority: 1.0, changeFrequency: "daily" as const },
    { path: "/pricing", priority: 0.8, changeFrequency: "weekly" as const },
    { path: "/features", priority: 0.8, changeFrequency: "weekly" as const },
    { path: "/about", priority: 0.7, changeFrequency: "monthly" as const },
    { path: "/blog", priority: 0.7, changeFrequency: "weekly" as const },
    { path: "/contact", priority: 0.5, changeFrequency: "monthly" as const },
    { path: "/privacy", priority: 0.5, changeFrequency: "monthly" as const },
    { path: "/terms", priority: 0.5, changeFrequency: "monthly" as const },
    { path: "/refund", priority: 0.5, changeFrequency: "monthly" as const },
    { path: "/return", priority: 0.5, changeFrequency: "monthly" as const },
    { path: "/shipping-returns", priority: 0.5, changeFrequency: "monthly" as const },
  ];

  return candidates
    .filter((candidate) => routeExists(candidate.path))
    .map((candidate) => ({
      url: `${baseUrl}${candidate.path === "/" ? "" : candidate.path}`,
      lastModified: new Date(),
      changeFrequency: candidate.changeFrequency,
      priority: candidate.priority,
    }));
}
